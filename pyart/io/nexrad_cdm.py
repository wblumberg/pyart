"""
pyart.io.nexrad_cdm
===================

Functions for accessing Common Data Model (CDM) NEXRAD Level 2 files.

.. autosummary::
    :toctree: generated/

    read_nexrad_cdm
    _gen_vnames
    _radar_from_cdm
    CDM_FIELD_MAPPING
    NEXRAD_METADATA

"""

from datetime import datetime, timedelta

import netCDF4
import numpy as np

from .radar import Radar
from .common import get_metadata, make_time_unit_str
from .nexrad_common import NEXRAD_METADATA


def read_nexrad_cdm(filename, field_mapping=None, field_metadata=None):
    """
    Read a Common Data Model (CDM) NEXRAD Level 2 file.

    Parameters
    ----------
    filename : str
        File name or URL of a Common Data Model (CDM) NEXRAD Level 2 file.
        File of in this format can be created using the NetCDF Java Library
        tools [1]_.  A URL of a OPeNDAP file on the UCAR THREDDS Data
        Server [2]_ is also accepted the netCDF4 library has been compiled
        with OPeNDAP support.
    field_mapping : None or dict, optional
        Dictionary mapping CDM variables to the corresponding field names in
        the radar objects returned. None will use :data:`CDM_FIELD_MAPPING`.
        which also served as an example of the format for this parameter.
        If a dictionary parameter is used it must have the same dictionary
        keys as CDM_FIELD_MAPPING.  In addition, field_metadata must also be
        provided which contains the field metadata for the fields specified.
    field_metadata : None or dict, optional
        Metadata for the fields specified by field_mapping, None will use the
        field metadata provided in :data:`NEXRAD_METADATA`, which also serves
        as an example of the format for this parameter.  This metadata will
        be used for the field in the created radar objects returned.

    Returns
    -------
    refl_hi : Radar
        Radar object containing the super resolution reflectivity field.
    dopl_hi : Radar
        Radar object containing the super resolution doppler fields present.
        Possible fields in the radar are: velocity, spectrum_width,
        differential_reflectivity, differential_phase, and
        correlation_coefficient.
    refl_sd : Radar
        Radar object containing the standard resolution reflectivity field.
    dopl_sd : Radar
        Radar object containing the standard resolution doppler fields.

    References
    ----------
    .. [1] http://www.unidata.ucar.edu/software/netcdf-java/documentation.htm
    .. [2] http://thredds.ucar.edu/thredds/catalog.html

    """
    # parse field_mapping and field_metadata parameters
    if field_mapping is None:
        field_mapping = CDM_FIELD_MAPPING.copy()
    if field_metadata is None:
        field_metadata = NEXRAD_METADATA.copy()

    dataset = netCDF4.Dataset(filename)
    dattrs = dataset.ncattrs()
    dvars = dataset.variables
    if 'cdm_data_type' not in dattrs or dataset.cdm_data_type != 'RADIAL':
        raise IOError('%s is not a valid CDM NetCDF file' % (filename))

    # determine the scan information
    scan_info = _scan_info(dvars)
    radials_per_scan = [max(s['nradials']) for s in scan_info]
    ngates_per_scan = [max(s['ngates']) for s in scan_info]
    ngates = max(ngates_per_scan)
    nrays = sum(radials_per_scan)
    nsweeps = len(scan_info)

    # time
    time = get_metadata('time')
    tdata = np.empty((nrays, ), dtype='float64')
    start = 0
    for scan_dic in scan_info:
        time_var = scan_dic['time_vars'][0]
        time_index = scan_dic['index'][0]
        nradials = scan_dic['nradials'][0]

        tdata[start:start + nradials] = dvars[time_var][time_index]
        start += nradials

    first_time_var = scan_info[0]['time_vars'][0]
    time_start = datetime.strptime(dvars[first_time_var].units[-20:],
                                   "%Y-%m-%dT%H:%M:%SZ")
    time_start = time_start + timedelta(seconds = int(tdata[0]/1000))
    time['data'] = tdata/1000. - int(tdata[0]/1000)
    time['units'] = make_time_unit_str(time_start)

    # range
    _range = get_metadata('range')

    max_ngates_scan_index = ngates_per_scan.index(ngates)
    scan_dic = scan_info[max_ngates_scan_index]
    max_ngates_moment_index = scan_dic['ngates'].index(ngates)
    distance_var = scan_dic['distance_vars'][max_ngates_moment_index]
    _range['data'] = dvars[distance_var][:]

    # fields
    # XXX

    shape = (nrays, ngates)
    fdata = {
        'Reflectivity':
            np.ma.masked_equal(np.ones(shape, dtype='float32'), 1),
        'RadialVelocity':
            np.ma.masked_equal(np.ones(shape, dtype='float32'), 1),
        'SpectrumWidth':
            np.ma.masked_equal(np.ones(shape, dtype='float32'), 1),
        'DifferentialReflectivity':
            np.ma.masked_equal(np.ones(shape, dtype='float32'), 1),
        'CorrelationCoefficient':
            np.ma.masked_equal(np.ones(shape, dtype='float32'), 1),
        'DifferentialPhase':
            np.ma.masked_equal(np.ones(shape, dtype='float32'), 1),
    }

    start = 0
    for scan_dic in scan_info:
        nradials = scan_dic['nradials'][0]
        for i, moment in enumerate(scan_dic['moments']):

            idx = scan_dic['index'][i]
            m_ngates = scan_dic['ngates'][i]
            m_nradials = scan_dic['nradials'][i]

            moment_var = dvars[moment]
            moment_var.set_auto_maskandscale(False)

            # mask, scale and offset
            raw_moment_data = moment_var[idx][:, :m_ngates]
            if '_Unsigned' in moment_var.ncattrs():
                if raw_moment_data.dtype == np.int8:
                    raw_moment_data = raw_moment_data.view('uint8')
                if raw_moment_data.dtype == np.int16:
                    raw_moment_data = raw_moment_data.view('uint16')

            raw_moment_data = np.ma.masked_less_equal(raw_moment_data, 1)

            if 'scale_factor' in moment_var.ncattrs():
                scale = moment_var.scale_factor
            else:
                scale = 1.0

            if 'add_offset' in moment_var.ncattrs():
                add_offset = moment_var.add_offset
            else:
                add_offset = 0.0

            m_data = raw_moment_data * scale + add_offset

            if moment.endswith('_HI'):
                fdata_name = moment[:-3]
            else:
                fdata_name = moment

            if fdata_name == 'Reflectivity':
                print "DEBUG"
                print "moment", moment
                print "idx", idx
                print "m_data shape and dtype:", m_data.shape, m_data.dtype
                print "m_ngates", m_ngates
            fdata[fdata_name][start:start + m_nradials, :m_ngates] = m_data

        start += nradials
    fields = {}
    for moment_name, moment_data in fdata.iteritems():
        field_name = field_mapping[moment_name]
        field_dic = field_metadata[field_name].copy()
        field_dic['_FillValue'] = -9999.0
        field_dic['data'] = moment_data
        fields[field_name] = field_dic

    # metadata
    metadata = {'original_container': 'NEXRAD Level II'}
    # additional required CF/Radial metadata set to blank strings
    metadata['title'] = ''
    metadata['institution'] = ''
    metadata['references'] = ''
    metadata['source'] = ''
    metadata['comment'] = ''
    metadata['instrument_name'] = ''

    # scan_type
    scan_type = 'ppi'

    # latitude, longitude, altitude
    latitude = get_metadata('latitude')
    longitude = get_metadata('longitude')
    altitude = get_metadata('altitude')
    latitude['data'] = np.array([dataset.StationLatitude], dtype='float64')
    longitude['data'] = np.array([dataset.StationLongitude], dtype='float64')
    altitude['data'] = np.array([dataset.StationElevationInMeters],
                                dtype='float64')

    # sweep_number, sweep_mode, fixed_angle, sweep_start_ray_index
    # sweep_end_ray_index
    sweep_number = get_metadata('sweep_number')
    sweep_mode = get_metadata('sweep_mode')
    sweep_start_ray_index = get_metadata('sweep_start_ray_index')
    sweep_end_ray_index = get_metadata('sweep_end_ray_index')

    sweep_number['data'] = np.arange(nsweeps, dtype='int32')
    sweep_mode['data'] = np.array(nsweeps * ['azimuth_surveillance'])
    rays_per_scan = list(radials_per_scan)
    sweep_end_ray_index['data'] = np.cumsum(rays_per_scan, dtype='int32') - 1

    rays_per_scan.insert(0, 0)
    sweep_start_ray_index['data'] = np.cumsum(rays_per_scan[:-1],
                                              dtype='int32')


    # azimuth, elevation, fixed_angle
    azimuth = get_metadata('azimuth')
    elevation = get_metadata('elevation')
    fixed_angle = get_metadata('fixed_angle')

    azim_data = np.empty((nrays, ), dtype='float32')
    elev_data = np.empty((nrays, ), dtype='float32')
    fxan_data = np.empty((nsweeps, ), dtype='float32')
    start = 0
    for scan_index, scan_dic in enumerate(scan_info):
        azimuth_var = scan_dic['azimuth_vars'][0]
        elevation_var = scan_dic['elevation_vars'][0]
        time_index = scan_dic['index'][0]
        nradials = scan_dic['nradials'][0]

        azim_data[start:start + nradials] = dvars[azimuth_var][time_index]
        elev_data[start:start + nradials] = dvars[elevation_var][time_index]
        fxan_data[scan_index] = np.mean(dvars[elevation_var][time_index])

        start += nradials

    azimuth['data'] = azim_data
    elevation['data'] = elev_data
    fixed_angle['data'] = fxan_data

    return Radar(
        time, _range, fields, metadata, scan_type,
        latitude, longitude, altitude,
        sweep_number, sweep_mode, fixed_angle, sweep_start_ray_index,
        sweep_end_ray_index,
        azimuth, elevation,
        instrument_parameters=None)


def _scan_info(dvars):
    """ Return a list of information on the scans in the volume. """
    # determine the time of the sweep start
    time_variables = [k for k in dvars.keys() if k.startswith('time')]

    scan_start_times = set([])
    for var in time_variables:
        for time in dvars[var][:,0]:
            scan_start_times.add(time)
    scan_start_times = list(scan_start_times)
    scan_start_times.sort()

    # build the scan_info list
    time_var_to_moment = {          # time variable to moment conversion
        'timeR': 'Reflectivity',
        'timeV': 'RadialVelocity',
        'timeD': 'DifferentialReflectivity',
        'timeC': 'CorrelationCoefficient',
        'timeP': 'DifferentialPhase',
        'timeR_HI': 'Reflectivity_HI',
        'timeV_HI': 'RadialVelocity_HI',
        'timeD_HI': 'DifferentialReflectivity_HI',
        'timeC_HI': 'CorrelationCoefficient_HI',
        'timeP_HI': 'DifferentialPhase_HI',
    }

    scan_info = [{'start_time': t, 'time_vars':[], 'moments':[],
                  'nradials':[], 'ngates':[], 'elevation_vars':[],
                  'azimuth_vars':[], 'distance_vars':[], 'index':[]}
                 for t in scan_start_times]

    for time_var in time_variables:
        for time_var_i, time in enumerate(dvars[time_var][:,0]):

            scan_index = scan_start_times.index(time)
            scan_dic = scan_info[scan_index]
            moment  = time_var_to_moment[time_var]
            _populate_scan_dic(scan_dic, time_var, time_var_i, moment, dvars)

            # corner cases, timeV is a dimension for RadialVelocity AND
            # SpectrumWidth
            if time_var == 'timeV':
                _populate_scan_dic(scan_dic, time_var, time_var_i,
                                   'SpectrumWidth', dvars)
            if time_var == 'timeV_HI':
                _populate_scan_dic(scan_dic, time_var, time_var_i,
                                   'SpectrumWidth_HI', dvars)

    return scan_info

def _populate_scan_dic(scan_dic, time_var, time_var_i, moment, dvars):
    """ Populate a dictionary in the scan_info list. """
    if time_var.endswith('HI'):
        var_suffix = time_var[-4:]
    else:
        var_suffix = time_var[-1:]

    ngates = dvars['numGates' + var_suffix][time_var_i]
    nradials = dvars['numRadials' + var_suffix][time_var_i]

    scan_dic['time_vars'].append(time_var)
    scan_dic['index'].append(time_var_i)
    scan_dic['moments'].append(moment)
    scan_dic['elevation_vars'].append('elevation' + var_suffix)
    scan_dic['azimuth_vars'].append('azimuth' + var_suffix)
    scan_dic['distance_vars'].append('distance' + var_suffix)
    scan_dic['ngates'].append(ngates)
    scan_dic['nradials'].append(nradials)
    return



def read_nexrad_cdm_old(filename, field_mapping=None, field_metadata=None):
    """
    Read a Common Data Model (CDM) NEXRAD Level 2 file.

    Parameters
    ----------
    filename : str
        File name or URL of a Common Data Model (CDM) NEXRAD Level 2 file.
        File of in this format can be created using the NetCDF Java Library
        tools [1]_.  A URL of a OPeNDAP file on the UCAR THREDDS Data
        Server [2]_ is also accepted the netCDF4 library has been compiled
        with OPeNDAP support.
    field_mapping : None or dict, optional
        Dictionary mapping CDM variables to the corresponding field names in
        the radar objects returned. None will use :data:`CDM_FIELD_MAPPING`.
        which also served as an example of the format for this parameter.
        If a dictionary parameter is used it must have the same dictionary
        keys as CDM_FIELD_MAPPING.  In addition, field_metadata must also be
        provided which contains the field metadata for the fields specified.
    field_metadata : None or dict, optional
        Metadata for the fields specified by field_mapping, None will use the
        field metadata provided in :data:`NEXRAD_METADATA`, which also serves
        as an example of the format for this parameter.  This metadata will
        be used for the field in the created radar objects returned.

    Returns
    -------
    refl_hi : Radar
        Radar object containing the super resolution reflectivity field.
    dopl_hi : Radar
        Radar object containing the super resolution doppler fields present.
        Possible fields in the radar are: velocity, spectrum_width,
        differential_reflectivity, differential_phase, and
        correlation_coefficient.
    refl_sd : Radar
        Radar object containing the standard resolution reflectivity field.
    dopl_sd : Radar
        Radar object containing the standard resolution doppler fields.

    References
    ----------
    .. [1] http://www.unidata.ucar.edu/software/netcdf-java/documentation.htm
    .. [2] http://thredds.ucar.edu/thredds/catalog.html

    """
    # parse field_mapping and field_metadata parameters
    if field_mapping is None:
        field_mapping = CDM_FIELD_MAPPING.copy()
    if field_metadata is None:
        field_metadata = NEXRAD_METADATA.copy()

    dataset = netCDF4.Dataset(filename)
    dattrs = dataset.ncattrs()
    if 'cdm_data_type' not in dattrs or dataset.cdm_data_type != 'RADIAL':
        raise IOError('%s is not a valid CDM NetCDF file' % (filename))

    # Might need to add a check to see if all fields/resolution are present.
    refl_hi = _radar_from_cdm(dataset, _gen_vnames('refl', True),
                              field_mapping, field_metadata)
    dopl_hi = _radar_from_cdm(dataset, _gen_vnames('doppler', True),
                              field_mapping, field_metadata)
    refl_sd = _radar_from_cdm(dataset, _gen_vnames('refl', False),
                              field_mapping, field_metadata)
    dopl_sd = _radar_from_cdm(dataset, _gen_vnames('doppler', False),
                              field_mapping, field_metadata)
    return refl_hi, dopl_hi, refl_sd, dopl_sd


# default mappings from CDM dataset variables to Radar object field names
CDM_FIELD_MAPPING = {
    'Reflectivity_HI': 'reflectivity',
    'RadialVelocity_HI': 'velocity',
    'SpectrumWidth_HI': 'spectrum_width',
    'DifferentialReflectivity_HI': 'differential_reflectivity',
    'DifferentialPhase_HI': 'differential_phase',
    'CorrelationCoefficient_HI': 'correlation_coefficient',
    'Reflectivity': 'reflectivity',
    'RadialVelocity': 'velocity',
    'SpectrumWidth': 'spectrum_width',
    'DifferentialReflectivity': 'differential_reflectivity',
    'DifferentialPhase': 'differential_phase',
    'CorrelationCoefficient': 'correlation_coefficient'
}


def _gen_vnames(field, high_res):
    """
    Return a dictionary of variables/dimension names in a CDM dataset.

    Parameters
    ----------
    field : 'refl' or 'doppler'
        Type of fields to generate dictionary for.
    high_res: bool
        True if the fields are high resolution.

    Returns
    -------
    vnames : dic
        Dictionary of variable and dimension names in the thredds server
        dataset for a given field type.  For use as the vnames parameter in
        :py:func:`_radar_from_cdm`.

    """
    if field == 'refl':
        suffix = 'R'
        fields = ['Reflectivity']
    else:
        suffix = 'V'
        fields = ['RadialVelocity', 'SpectrumWidth',
                  'DifferentialReflectivity', 'CorrelationCoefficient',
                  'DifferentialPhase']
        # The RadialVelocity and SpectrumWidth fields have
        # variables/coordinate suffixed by a V, where as the
        # DifferentialReflectivity, CorrelationCoefficient, and
        # DifferentialPhase fields have their own suffixes (D, C, P)
        # These all appear to have the values, but  this has not
        # been verified and may by incorrect.  Going to this assumption
        # these fields are refered to in this function as doppler fields.

    if high_res:
        suffix += '_HI'
        fields = [f + '_HI' for f in fields]

    # build the variables as foo{R, V, D, C, P}{_HI}.
    keys = ['scan', 'radial', 'gate', 'time', 'elevation', 'azimuth',
            'distance', 'numRadials', 'numGates']
    vnames = dict([(k, k + suffix) for k in keys])
    vnames['fields'] = fields
    return vnames


def _radar_from_cdm(dataset, vnames, field_mapping, field_metadata):
    """
    Return a Radar from a CDM dataset.

    Parameters
    ----------
    dataset : Dataset
        CDM dataset with NEXRAD Level II data.
    vnames : dict
        Variable and dimension names in dataset which will be used to
        populate the Radar.
    field_mapping : dict
        Mapping between CDM variable and radar field names.  See
        :func:`read_nexrad_cdm` for details.
    field_metadata
        Metadata for the field specified in field_mapping.  See
        :func:`read_nexrad_cdm` for details.

    Returns
    -------
    radar : Radar
        Radar containing the requested fields.

    """
    dvars = dataset.variables

    # dimensionality
    nsweeps = len(dataset.dimensions[vnames['scan']])
    rays_per_sweep = len(dataset.dimensions[vnames['radial']])
    ngates = len(dataset.dimensions[vnames['gate']])
    nrays = nsweeps * rays_per_sweep

    # time
    time = get_metadata('time')
    # time in msecs, convert to seconds
    time['data'] = dvars[vnames['time']][:].reshape(nrays) / 1000.

    # change unit string from 'msecs since ...' to 'seconds since ...'
    units = dvars[vnames['time']].units
    time['units'] = 'seconds ' + units[6:]

    # _range
    _range = get_metadata('range')
    _range['data'] = dvars[vnames['distance']][:]
    _range['meters_to_center_of_first_gate'] = _range['data'][0]
    _range['meters_between_gates'] = _range['data'][1] - _range['data'][0]

    # fields
    fields = {}
    for field in vnames['fields']:

        if field not in dvars:  # do nothing if field is not present
            continue

        field_name = field_mapping[field]
        field_dic = field_metadata[field_name].copy()
        field_dic['_FillValue'] = -9999.0

        # extract the field
        fvar = dvars[field]
        fvar.set_auto_maskandscale(False)
        raw_fdata = fvar[:]

        # mask, reshape, scale and offset
        raw_fdata = np.ma.masked_less_equal(raw_fdata, 1)
        raw_fdata = raw_fdata.reshape(-1, raw_fdata.shape[-1])

        if 'scale_factor' in fvar.ncattrs():
            scale = fvar.scale_factor
        else:
            scale = 1.0

        if 'add_offset' in fvar.ncattrs():
            add_offset = fvar.add_offset
        else:
            add_offset = 0.0

        field_dic['data'] = raw_fdata * scale + add_offset

        # add the field dictionary to the fields dictionary
        fields[field_name] = field_dic

    # metadata
    metadata = {'original_container': 'NEXRAD Level 2 Archive - Thredds'}
    for key in dataset.ncattrs():
        metadata[key] = dataset.getncattr(key)

    # additional required CF/Radial metadata, blank if not present
    if 'Title' in dataset.ncattrs():
        metadata['title'] = dataset.Title
    else:
        metadata['title'] = ''
    metadata['institution'] = ''
    metadata['references'] = ''
    metadata['source'] = ''
    metadata['comment'] = ''
    metadata['instrument_name'] = ''

    # scan_type
    scan_type = 'ppi'

    # latitude, longitude, altitude
    latitude = get_metadata('latitude')
    longitude = get_metadata('longitude')
    altitude = get_metadata('altitude')
    latitude['data'] = np.array([dataset.StationLatitude], dtype='float64')
    longitude['data'] = np.array([dataset.StationLongitude], dtype='float64')
    altitude['data'] = np.array([dataset.StationElevationInMeters],
                                dtype='float64')

    # sweep_number, sweep_mode, sweep_start_ray_index,sweep_end_ray_index
    sweep_number = get_metadata('sweep_number')
    sweep_mode = get_metadata('sweep_mode')
    sweep_start_ray_index = get_metadata('sweep_start_ray_index')
    sweep_end_ray_index = get_metadata('sweep_end_ray_index')

    rays_per_sweep = len(dataset.dimensions[vnames['radial']])

    sweep_number['data'] = np.arange(nsweeps, dtype='int32')
    sweep_mode['data'] = np.array(nsweeps * ['azimuth_surveillance'])
    ssri = np.arange(nsweeps, dtype='int32') * rays_per_sweep
    seri = np.arange(1, nsweeps + 1, dtype='int32') * rays_per_sweep - 1
    sweep_start_ray_index['data'] = ssri
    sweep_end_ray_index['data'] = seri

    # azimuth, elevation, fixed_angle
    azimuth = get_metadata('azimuth')
    elevation = get_metadata('elevation')
    fixed_angle = get_metadata('fixed_angle')

    azimuth['data'] = dvars[vnames['azimuth']][:].reshape(-1)
    elevation['data'] = dvars[vnames['elevation']][:].reshape(-1)
    fixed_angle['data'] = dvars[vnames['elevation']][:].reshape(-1)

    return Radar(
        time, _range, fields, metadata, scan_type,
        latitude, longitude, altitude,
        sweep_number, sweep_mode, fixed_angle, sweep_start_ray_index,
        sweep_end_ray_index,
        azimuth, elevation,
        instrument_parameters=None)
