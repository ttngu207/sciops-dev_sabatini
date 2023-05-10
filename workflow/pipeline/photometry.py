from __future__ import annotations
import datajoint as dj
import pandas as pd
import numpy as np
import warnings
from pathlib import Path
import tomli
import tdt
import scipy.io as spio
from scipy import signal
from scipy.fft import fft, ifft, rfft
from copy import deepcopy

from element_interface.utils import find_full_path
from workflow import db_prefix
from workflow.pipeline import session, subject, lab, reference
from workflow.utils.paths import get_raw_root_data_dir
import workflow.utils.photometry_preprocessing as pp
from workflow.utils import demodulation


logger = dj.logger
schema = dj.schema(db_prefix + "photometry")


@schema
class SensorProtein(dj.Lookup):
    definition = """            
    sensor_protein_name : varchar(16)  # (e.g., GCaMP, dLight, etc)
    """


@schema
class LightSource(dj.Lookup):
    definition = """
    light_source_name   : varchar(16)
    """
    contents = zip(["Plexon LED", "Laser"])


@schema
class ExcitationWavelength(dj.Lookup):
    definition = """
    excitation_wavelength   : smallint  # (nm)
    """


@schema
class EmissionColor(dj.Lookup):
    definition = """
    emission_color     : varchar(10) 
    ---
    wavelength=null    : smallint  # (nm)
    """


@schema
class FiberPhotometry(dj.Imported):
    definition = """
    -> session.Session
    ---
    -> [nullable] LightSource
    raw_sample_rate         : float         # sample rate of the raw data (in Hz) 
    beh_synch_signal=null   : longblob      # signal for behavioral synchronization from raw data
    """

    class Fiber(dj.Part):
        definition = """ 
        -> master
        fiber_id            : tinyint unsigned
        -> reference.Hemisphere
        ---
        notes=''             : varchar(1000)  
        """

    class DemodulatedTrace(dj.Part):
        definition = """ # demodulated photometry traces
        -> master.Fiber
        trace_name          : varchar(8)  # (e.g., raw, detrend)
        -> EmissionColor
        ---
        -> [nullable] SensorProtein          
        -> [nullable] ExcitationWavelength
        demod_sample_rate   : float       # sample rate of the demodulated data (in Hz) 
        trace               : longblob    # demodulated photometry traces
        """

    def make(self, key):
        
        # Find data dir
        #first determine data type e.g. raw matlab, processed matlab, or tdt
        session_dir = (session.SessionDirectory & key).fetch1("session_dir")
        session_full_dir: Path = find_full_path(get_raw_root_data_dir(), session_dir)
        photometry_dir = session_full_dir / "Photometry"

        # Read from the meta_info.toml in the photometry folder if exists
        meta_info_file = list(photometry_dir.glob("*.toml"))[0]
        meta_info = {}
        try:
            with open(meta_info_file, "rb") as f:
                meta_info = tomli.load(f)
        except FileNotFoundError:
            logger.info("meta info is missing")
        light_source_name = meta_info.get("Experimental_Details").get("light_source")

        # Scan directory for data format
        # If there is a .tdt file, then it is a tdt data and enter tdt_data mode
        # If there is a .mat file, then it is a matlab data and enter matlab_data mode
        # If there is a timeseries2.mat file, then it is demux matlab data and enter demux_matlab_data mode  
        if len(list(photometry_dir.glob("processed*.mat"))) > 0:
            data_format = "matlab_data"
            matlab_data: dict = spio.loadmat(
            next(photometry_dir.glob("processed*.mat")), simplify_cells=True)[list(matlab_data.keys())[3]]
        elif len(list(photometry_dir.glob("*timeseries_2.mat"))) > 0:
            data_format = "demux_matlab_data"
            demux_matlab_data: list[dict] = spio.loadmat(
                next(photometry_dir.glob("*timeseries_2.mat")), simplify_cells=True
            )["timeSeries"]
        else:
            data_format = "tdt_data"
            tdt_data: tdt.StructType = tdt.read_block(photometry_dir)      
        
        ## Enter into different data format mode
        if data_format == "matlab_data":
            del matlab_data
            raw_sample_rate = None
            beh_synch_signal = demux_matlab_data[0]["time_offset"]
            
        elif data_format == "demux_matlab_data":
            #demux_matlab_data
            del demux_matlab_data
            raw_sample_rate = None
            beh_synch_signal = demux_matlab_data[0]["time_offset"]

            #Get index of traces
            trace_indices = meta_info.get("Signal_Indices")
            carrier_g_right = trace_indices.get("carrier_g_right", None)
            carrier_r_right =trace_indices.get("carrier_r_right", None)
            photom_g_right = trace_indices.get("photom_g_right", None)
            photom_r_right = trace_indices.get("photom_r_right", None)
            carrier_g_left = trace_indices.get("carrier_g_left", None)
            carrier_r_left = trace_indices.get("carrier_r_left", None)
            photom_g_left = trace_indices.get("photom_g_left", None)
            photom_r_left = trace_indices.get("photom_r_left", None)

            # Get demodulated sample rate
            demod_sample_rate_g_left = demux_matlab_data[carrier_g_left]["demux_freq"]
            demod_sample_rate_r_left = demux_matlab_data[carrier_r_left]["demux_freq"]
            demod_sample_rate_g_right = demux_matlab_data[carrier_g_right]["demux_freq"]
            demod_sample_rate_r_right = demux_matlab_data[carrier_r_right]["demux_freq"]
            

            fiber_id = meta_info.get("Experimental_Details").get("Fiber")
            hemisphere = meta_info.get("Experimental_Details").get("hemisphere")
            fiber_notes = meta_info.get("Experimental_Details").get("notes", None)

            fiber_list.append(
                {
                    **key,
                    "fiber_id": fiber_id,
                    "hemisphere": hemisphere,
                    "notes": fiber_notes,
                }
                 )
             # Populate EmissionColor if present
                
            emission_wavelength_g_left = (
                    meta_info.get("Experimental_Details")
                    .get("emission_wavelength_g_left", None)
                )
            emission_wavelength_r_left = (
                    meta_info.get("Experimental_Details")
                    .get("emission_wavelength_r_left", None)
                )
            emission_color_g_left = (
                    meta_info.get("Experimental_Details")
                    .get("emission_color_g_left", None)
                )
            emission_color_r_left = (
                    meta_info.get("Experimental_Details")
                    .get("emission_color_r_left", None)
                )
            emission_wavelength_g_right = (
                    meta_info.get("Experimental_Details")
                    .get("emission_wavelength_g_right", None)
                )
            emission_wavelength_r_right = (
                    meta_info.get("Experimental_Details")
                    .get("emission_wavelength_r_right", None)
                )
            emission_color_g_right = (
                    meta_info.get("Experimental_Details")
                    .get("emission_color_g_right", None)
                )
            emission_color_r_right = (
                    meta_info.get("Experimental_Details")
                    .get("emission_color_r_right", None)
                )


            EmissionColor.insert1(
                    {
                        "emission_color_g_left": emission_color_g_left,
                        "emission_color_r_left": emission_color_r_left,
                        "wavelength_g_left": emission_wavelength_g_left,
                        "wavelength_r_left": emission_wavelength_r_left,
                        "emission_color_g_right": emission_color_g_right,
                        "emission_color_r_right": emission_color_r_right,
                        "wavelength_g_right": emission_wavelength_g_right,
                        "wavelength_r_right": emission_wavelength_r_right,
                    },
                    skip_duplicates=True,
                )
                # Populate SensorProtein if present
            sensor_protein_g_left = (
                    meta_info.get("Experimental_Details")
                    .get("sensor_protein_name_g_left", None)
                    )
            sensor_protein_r_left = (
                    meta_info.get("Experimental_Details")
                    .get("sensor_protein_name_r_left", None)
                    )
            sensor_protein_g_right = (
                    meta_info.get("Experimental_Details")
                    .get("sensor_protein_name_g_right", None)
                    )
            sensor_protein_r_right = (
                    meta_info.get("Experimental_Details")
                    .get("sensor_protein_name_r_right", None)
                    )
            if sensor_protein_g_left:
                    logger.info(
                        f"{sensor_protein_g_left} is inserted into {__name__}.SensorProtein"
                    )
                    SensorProtein.insert1(
                        {"sensor_protein_name_g_left": sensor_protein_g_left}, skip_duplicates=True
                    )
            if sensor_protein_r_left:
                    logger.info(
                        f"{sensor_protein_r_left} is inserted into {__name__}.SensorProtein"
                    )
                    SensorProtein.insert1(
                        {"sensor_protein_name_r_left": sensor_protein_r_left}, skip_duplicates=True
                    )
            if sensor_protein_g_right:
                    logger.info(
                        f"{sensor_protein_g_right} is inserted into {__name__}.SensorProtein"
                    )
                    SensorProtein.insert1(
                        {"sensor_protein_name_g_right": sensor_protein_g_right}, skip_duplicates=True
                    )
            if sensor_protein_r_right:
                    logger.info(
                        f"{sensor_protein_r_right} is inserted into {__name__}.SensorProtein"
                    )
                    SensorProtein.insert1(
                        {"sensor_protein_name_r_right": sensor_protein_r_right}, skip_duplicates=True
                    )

                # Populate ExcitationWavelength if present
            excitation_wavelength_g_left = (
                    meta_info.get("Experimental_Details")
                    .get("excitation_wavelength_g_left", {})
                )

            if excitation_wavelength_g_left:
                    logger.info(
                        f"{excitation_wavelength_g_left} is inserted into {__name__}.ExcitationWavelength"
                    )
                    ExcitationWavelength.insert1(
                        {"excitation_wavelength_g_left": excitation_wavelength_g_left},
                        skip_duplicates=True,
                    )
            excitation_wavelength_r_left = (
                    meta_info.get("Experimental_Details")
                    .get("excitation_wavelength_r_left", {})
                    )

            if excitation_wavelength_r_left:
                    logger.info(
                        f"{excitation_wavelength_r_left} is inserted into {__name__}.ExcitationWavelength"
                    )
                    ExcitationWavelength.insert1(
                        {"excitation_wavelength_r_left": excitation_wavelength_r_left},
                        skip_duplicates=True,
                    )
            excitation_wavelength_g_right = (
                    meta_info.get("Experimental_Details")
                    .get("excitation_wavelength_g_right", {})
                )

            if excitation_wavelength_g_right:
                    logger.info(
                        f"{excitation_wavelength_g_right} is inserted into {__name__}.ExcitationWavelength"
                    )
                    ExcitationWavelength.insert1(
                        {"excitation_wavelength_g_right": excitation_wavelength_g_right},
                        skip_duplicates=True,
                    )
            excitation_wavelength_r_right = (
                    meta_info.get("Experimental_Details")
                    .get("excitation_wavelength_r_right", {})
                )

            if excitation_wavelength_r_right:
                    logger.info(
                        f"{excitation_wavelength_r_right} is inserted into {__name__}.ExcitationWavelength"
                    )
                    ExcitationWavelength.insert1(
                        {"excitation_wavelength_r_right": excitation_wavelength_r_right},
                        skip_duplicates=True,
                    )

                ##pull out the data from the matlab file
            for sensor_protein in ["g_left", "r_left", "g_right", "r_right"]:
                    if sensor_protein == "g_left":
                        photometry_demux_g_left = demux_matlab_data[photom_g_left]['data']
                    elif sensor_protein == "r_left":
                        photometry_demux_r_left = demux_matlab_data[photom_r_left]['data']
                    elif sensor_protein == "g_right":
                        photometry_demux_g_right = demux_matlab_data[photom_g_right]['data']
                    elif sensor_protein == "r_right":
                        photometry_demux_r_right = demux_matlab_data[photom_r_right]['data']
                    else:
                        raise ValueError("Sensor Protein must be g or r")
                    
                    demodulated_trace_list.append(
                    {
                        **key,
                        "fiber_id": fiber_id,
                        "hemisphere": hemisphere,
                        "trace_name": trace_name.split("_")[0],
                        "emission_color_g_left": emission_color_g_left,
                        "emission_color_r_left": emission_color_r_left,
                        "emission_color_g_right": emission_color_g_left,
                        "emission_color_r_right": emission_color_r_right,
                        "sensor_protein_name_g_left": sensor_protein_g_left,
                        "sensor_protein_name_r_left": sensor_protein_r_left,
                        "sensor_protein_name_g_right": sensor_protein_g_right,
                        "sensor_protein_name_r_right": sensor_protein_r_right,
                        "excitation_wavelength_g_left": excitation_wavelength_g_left,
                        "excitation_wavelength_r_left": excitation_wavelength_r_left,
                        "excitation_wavelength_g_right": excitation_wavelength_g_right,
                        "excitation_wavelength_r_right": excitation_wavelength_r_right,
                        "demod_sample_rate_g_left": demod_sample_rate_g_left,
                        "demod_sample_rate_r_left": demod_sample_rate_r_left,
                        "demod_sample_rate_g_right": demod_sample_rate_g_right,
                        "demod_sample_rate_r_right": demod_sample_rate_r_right,
                        "trace_g_left": photometry_demux_g_left,
                        "trace_r_left": photometry_demux_r_left,
                        "trace_g_right": photometry_demux_g_right,
                        "trace_r_right": photometry_demux_r_right,
                    }
                )
                #demux_matlab_data


        elif data_format == "tdt_data":
            #tdt_data             
            del tdt_data
            
            # Get trace indices from meta_info
            trace_indices = meta_info.get("Signal_Indices")
            carrier_g_right = tdt_data.streams.Fi1r.data[trace_indices.get("carrier_g_right", None)]
            carrier_r_right =tdt_data.streams.Fi1r.data[trace_indices.get("carrier_r_right", None)]
            photom_g_right = tdt_data.streams.Fi1r.data[trace_indices.get("photom_g_right", None)]
            photom_r_right = tdt_data.streams.Fi1r.data[trace_indices.get("photom_r_right", None)]
            carrier_g_left = tdt_data.streams.Fi2r.data[trace_indices.get("carrier_g_left", None)]
            carrier_r_left = tdt_data.streams.Fi2r.data [trace_indices.get("carrier_r_left", None)]
            photom_g_left = tdt_data.streams.Fi2r.data[trace_indices.get("photom_g_left", None)]
            photom_r_left = tdt_data.streams.Fi2r.data[trace_indices.get("photom_r_left", None)]

            #Get trace names and store in this list for ingestion
            raw_photom_list: list[dict]=[photom_g_right, photom_r_right, 
                                         photom_g_left, photom_r_left]
            raw_carrier_list: list[dict]=[carrier_g_right, carrier_r_right,
                                            carrier_g_left, carrier_r_left]

            
            # Get processing parameters
            processing_parameters = meta_info.get("Processing_Parameters")
            beh_synch_signal = processing_parameters.get("behavior_offset", 0)
            window = processing_parameters.get("z_window", 60)
            process_z = processing_parameters.get("z", False)
            set_carrier_g_right = processing_parameters.get("carrier_frequency_g_left", 0)
            set_carrier_r_right = processing_parameters.get("carrier_frequency_r_left", 0)
            set_carrier_g_left = processing_parameters.get("carrier_frequency_g_right", 0)
            set_carrier_r_left = processing_parameters.get("carrier_frequency_r_right", 0)
            bp_bw = processing_parameters.get("bandpass_bandwidth", 0.5)
            sampling_Hz = processing_parameters.get("sampling_frequency", None)
            downsample_Hz = processing_parameters.get("downsample_frequency", 200)
            demod_sample_rate = processing_parameters.get("demod_sample_rate", 200)
            transform = processing_parameters.get("transform", {})
            num_perseg = processing_parameters.get("no_per_segment", 216)
            n_overlap = processing_parameters.get("noverlap", 108)

            set_carrier_list: list[dict]=[set_carrier_g_right, set_carrier_r_right,
                                            set_carrier_g_left, set_carrier_r_left]
            


            #change window to reflect the sampling rate/downsample rate
            window1 = round(window * sampling_Hz)
            window2 = round(window * downsample_Hz)

            # Process traces
            if transform == "spectogram":
                calc_carry_list = demodulation.calc_carry(raw_carrier_list, sampling_Hz)
                for i in range(len(set_carrier_list)):
                    if calc_carry_list[i] != (set_carrier_list[i] >= calc_carry_list[i]+5 or set_carrier_list[i] <= calc_carry_list[i]-5):
                        warnings.warn("Calculated carrier frequency does not match set carrier frequency. Using calculated carrier frequency.")
                        set_carrier_list = calc_carry_list
                else:
                    calc_carry_list = calc_carry_list

                four_list = demodulation.four(raw_photom_list)
                z1_trace_list, power_spectra_list, t_list = demodulation.process_trace(
                                raw_photom_list, calc_carry_list,
                                sampling_Hz, window1, num_perseg, n_overlap)                 
            else:
                fiber_to_side_mapping = {1: "right", 2: "left"}
                color_mapping = {"g": "green", "r": "red", "b": "blue"}
                synch_signal_names = ["toBehSys", "fromBehSys"]
                demod_sample_rate = 600
                photometry_df, fibers, raw_sample_rate = demodulation.offline_demodulation(
                tdt_data, z=True, tau=0.05, downsample_fs=demod_sample_rate, bandpass_bw=20
                )

            #loop through each trace in raw_photom_list and raw_carrier_list
            #return the demodulated traces
            
          
        # Store data in this list for ingestion
            fiber_list: list[dict] = []
            demodulated_trace_list: list[dict] = []
                   
        # Get photometry traces for each fiber
            fiber_id = meta_info.get("Experimental_Details").get("Fiber")
            hemisphere = meta_info.get("Experimental_Details").get("hemisphere")
            fiber_notes = meta_info.get("Experimental_Details").get("notes", None)

            fiber_list.append(
                {
                    **key,
                    "fiber_id": fiber_id,
                    "hemisphere": hemisphere,
                    "notes": fiber_notes,
                }
                 )
             # Populate EmissionColor if present
                
            emission_wavelength_g_left = (
                    meta_info.get("Experimental_Details")
                    .get("emission_wavelength_g_left", None)
                )
            emission_wavelength_r_left = (
                    meta_info.get("Experimental_Details")
                    .get("emission_wavelength_r_left", None)
                )
            emission_color_g_left = (
                    meta_info.get("Experimental_Details")
                    .get("emission_color_g_left", None)
                )
            emission_color_r_left = (
                    meta_info.get("Experimental_Details")
                    .get("emission_color_r_left", None)
                )
            emission_wavelength_g_right = (
                    meta_info.get("Experimental_Details")
                    .get("emission_wavelength_g_right", None)
                )
            emission_wavelength_r_right = (
                    meta_info.get("Experimental_Details")
                    .get("emission_wavelength_r_right", None)
                )
            emission_color_g_right = (
                    meta_info.get("Experimental_Details")
                    .get("emission_color_g_right", None)
                )
            emission_color_r_right = (
                    meta_info.get("Experimental_Details")
                    .get("emission_color_r_right", None)
                )


            EmissionColor.insert1(
                    {
                        "emission_color_g_left": emission_color_g_left,
                        "emission_color_r_left": emission_color_r_left,
                        "wavelength_g_left": emission_wavelength_g_left,
                        "wavelength_r_left": emission_wavelength_r_left,
                        "emission_color_g_right": emission_color_g_right,
                        "emission_color_r_right": emission_color_r_right,
                        "wavelength_g_right": emission_wavelength_g_right,
                        "wavelength_r_right": emission_wavelength_r_right,
                    },
                    skip_duplicates=True,
                    )
                # Populate SensorProtein if present
            sensor_protein_g_left = (
                    meta_info.get("Experimental_Details")
                    .get("sensor_protein_name_g_left", None)
                    )
            sensor_protein_r_left = (
                    meta_info.get("Experimental_Details")
                    .get("sensor_protein_name_r_left", None)
                    )
            sensor_protein_g_right = (
                    meta_info.get("Experimental_Details")
                    .get("sensor_protein_name_g_right", None)
                    )
            sensor_protein_r_right = (
                    meta_info.get("Experimental_Details")
                    .get("sensor_protein_name_r_right", None)
                    )
            if sensor_protein_g_left:
                    logger.info(
                        f"{sensor_protein_g_left} is inserted into {__name__}.SensorProtein"
                    )
                    SensorProtein.insert1(
                        {"sensor_protein_name_g_left": sensor_protein_g_left}, skip_duplicates=True
                    )
            if sensor_protein_r_left:
                    logger.info(
                        f"{sensor_protein_r_left} is inserted into {__name__}.SensorProtein"
                    )
                    SensorProtein.insert1(
                        {"sensor_protein_name_r_left": sensor_protein_r_left}, skip_duplicates=True
                    )
            if sensor_protein_g_right:
                    logger.info(
                        f"{sensor_protein_g_right} is inserted into {__name__}.SensorProtein"
                    )
                    SensorProtein.insert1(
                        {"sensor_protein_name_g_right": sensor_protein_g_right}, skip_duplicates=True
                    )
            if sensor_protein_r_right:
                    logger.info(
                        f"{sensor_protein_r_right} is inserted into {__name__}.SensorProtein"
                    )
                    SensorProtein.insert1(
                        {"sensor_protein_name_r_right": sensor_protein_r_right}, skip_duplicates=True
                    )

                # Populate ExcitationWavelength if present
            excitation_wavelength_g_left = (
                    meta_info.get("Experimental_Details")
                    .get("excitation_wavelength_g_left", {})
                )

            if excitation_wavelength_g_left:
                    logger.info(
                        f"{excitation_wavelength_g_left} is inserted into {__name__}.ExcitationWavelength"
                    )
                    ExcitationWavelength.insert1(
                        {"excitation_wavelength_g_left": excitation_wavelength_g_left},
                        skip_duplicates=True,
                    )
            excitation_wavelength_r_left = (
                    meta_info.get("Experimental_Details")
                    .get("excitation_wavelength_r_left", {})
                    )

            if excitation_wavelength_r_left:
                    logger.info(
                        f"{excitation_wavelength_r_left} is inserted into {__name__}.ExcitationWavelength"
                    )
                    ExcitationWavelength.insert1(
                        {"excitation_wavelength_r_left": excitation_wavelength_r_left},
                        skip_duplicates=True,
                    )
            excitation_wavelength_g_right = (
                    meta_info.get("Experimental_Details")
                    .get("excitation_wavelength_g_right", {})
                )

            if excitation_wavelength_g_right:
                    logger.info(
                        f"{excitation_wavelength_g_right} is inserted into {__name__}.ExcitationWavelength"
                    )
                    ExcitationWavelength.insert1(
                        {"excitation_wavelength_g_right": excitation_wavelength_g_right},
                        skip_duplicates=True,
                    )
            excitation_wavelength_r_right = (
                    meta_info.get("Experimental_Details")
                    .get("excitation_wavelength_r_right", {})
                )

            if excitation_wavelength_r_right:
                    logger.info(
                        f"{excitation_wavelength_r_right} is inserted into {__name__}.ExcitationWavelength"
                    )
                    ExcitationWavelength.insert1(
                        {"excitation_wavelength_r_right": excitation_wavelength_r_right},
                        skip_duplicates=True,
                    )

            demodulated_trace_list = power_spectra_list
                    
            demodulated_trace_list.append(
                    {
                        **key,
                        "fiber_id": fiber_id,
                        "hemisphere": hemisphere,
                        "trace_name": trace_name.split("_")[0],
                        "emission_color_g_left": emission_color_g_left,
                        "emission_color_r_left": emission_color_r_left,
                        "emission_color_g_right": emission_color_g_left,
                        "emission_color_r_right": emission_color_r_right,
                        "sensor_protein_name_g_left": sensor_protein_g_left,
                        "sensor_protein_name_r_left": sensor_protein_r_left,
                        "sensor_protein_name_g_right": sensor_protein_g_right,
                        "sensor_protein_name_r_right": sensor_protein_r_right,
                        "excitation_wavelength_g_left": excitation_wavelength_g_left,
                        "excitation_wavelength_r_left": excitation_wavelength_r_left,
                        "excitation_wavelength_g_right": excitation_wavelength_g_right,
                        "excitation_wavelength_r_right": excitation_wavelength_r_right,
                        "demod_sample_rate_g_left": demod_sample_rate_g_left,
                        "demod_sample_rate_r_left": demod_sample_rate_r_left,
                        "demod_sample_rate_g_right": demod_sample_rate_g_right,
                        "demod_sample_rate_r_right": demod_sample_rate_r_right,
                        "trace_g_left": photometry_demux_g_left,
                        "trace_r_left": photometry_demux_r_left,
                        "trace_g_right": photometry_demux_g_right,
                        "trace_r_right": photometry_demux_r_right,
                    }
                )
                    #tdt_data

##Keep TDT blocks and MATLAB blocks completely seperate 

        # Populate FiberPhotometry
        logger.info(f"Populate {__name__}.FiberPhotometry")
        self.insert1(
            {
                **key,
                "light_source_name": light_source_name,
                "raw_sample_rate": raw_sample_rate,
                "beh_synch_signal": beh_synch_signal,
            }
        )

        # Populate FiberPhotometry.Fiber
        logger.info(f"Populate {__name__}.FiberPhotometry.Fiber")
        self.Fiber.insert(fiber_list)

        # Populate FiberPhotometry.DemodulatedTrace
        logger.info(f"Populate {__name__}.FiberPhotometry.DemodulatedTrace")
        self.DemodulatedTrace.insert(demodulated_trace_list)


@schema
class FiberPhotometrySynced(dj.Imported):
    definition = """
    -> FiberPhotometry
    ---
    timestamps   : longblob
    time_offset  : float     # time offset to synchronize the photometry traces to the master clock (in second)  
    sample_rate  : float     # target downsample rate of synced data (in Hz) 
    """

    class SyncedTrace(dj.Part):
        definition = """ # demodulated photometry traces
        -> master
        -> FiberPhotometry.Fiber
        trace_name          : varchar(8)  # (e.g., raw, detrend)
        -> EmissionColor
        ---
        trace      : longblob  
        """

    def make(self, key):

        # Parameters
        get_fiber_id = (
            lambda side: 1 if side.lower().startswith("r") else 2
        )  # map hemisphere to fiber id
        get_color = (
            lambda s: "green"
            if s.lower().startswith("g")
            else "red"
            if s.lower().startswith("r")
            else None
        )
        color_mapping = {"green": "grn"}
        synch_signal_names = ["toBehSys", "fromBehSys"]
        behavior_sample_rate = 200  # original behavioral sampling freq (Hz)
        target_downsample_rate = 50  # (Hz)
        downsample_factor = behavior_sample_rate / target_downsample_rate

        # Find data dir
        subject_id, session_dir = (session.SessionDirectory & key).fetch1(
            "subject", "session_dir"
        )
        session_full_dir: Path = find_full_path(get_raw_root_data_dir(), session_dir)
        behavior_dir = session_full_dir / "Behavior"

        # Fetch demodulated photometry traces from FiberPhotometry table
        query = (FiberPhotometry.Fiber * FiberPhotometry.DemodulatedTrace) & key

        photometry_dict = {}

        for row in query:
            trace_name = (
                "_".join([row["trace_name"], color_mapping[row["emission_color"]]])
                + row["hemisphere"][0].upper()
            )
            trace = row["trace"]
            photometry_dict[trace_name] = trace

        photometry_df = pd.DataFrame(
            (FiberPhotometry & key).fetch1("beh_synch_signal") | photometry_dict
        )
        # Get trace names e.g., ["detrend_grnR", "raw_grnR"]
        trace_names: list[str] = photometry_df.columns.drop(synch_signal_names).tolist()

        # Update df to start with first trial pulse from behavior system
        photometry_df = pp.handshake_behav_recording_sys(photometry_df)

        analog_df: pd.DataFrame = pd.read_csv(
            behavior_dir / f"{subject_id}_analog_filled.csv", index_col=0
        )
        analog_df["session_clock"] = analog_df.index * 0.005

        # Resample the photometry data and align to 200 Hz state transition behavioral data (analog_df)
        behavior_df: pd.DataFrame = pd.read_csv(
            behavior_dir / f"{subject_id}_behavior_df_full.csv", index_col=0
        )

        aligned_behav_photo_df, time_offset = pp.resample_and_align(
            analog_df, photometry_df, channels=trace_names
        )
        del analog_df

        # One more rolling z-score over the window length (60s * sampling freq (200Hz))
        win = round(60 * 200)

        for channel in trace_names:
            if "detrend" in channel:
                aligned_behav_photo_df[
                    f'z_{channel.split("_")[-1]}'
                ] = demodulation.rolling_z(aligned_behav_photo_df[channel], wn=win)
        aligned_behav_photo_df = aligned_behav_photo_df.iloc[win:-win].reset_index(
            drop=True
        )  # drop edges that now contain NaNs from rolling window

        # Drop unnecessary columns that we don't need to save
        photo_columns = trace_names + [
            f'z_{channel.split("_")[-1]}' for channel in trace_names[::3]
        ]  # trace_names[::((len(trace_names)//2)+1)]]]

        cols_to_keep = [
            "nTrial",
            "iBlock",
            "Cue",
            "ENL",
            "Select",
            "Consumption",
            "iSpout",
            "stateConsumption",
            "ENLP",
            "CueP",
            "nENL",
            "nCue",
            "session_clock",
        ]
        cols_to_keep.extend(photo_columns)

        timeseries_task_states_df: pd.DataFrame = deepcopy(
            aligned_behav_photo_df[cols_to_keep]
        )
        timeseries_task_states_df["trial_clock"] = (
            timeseries_task_states_df.groupby("nTrial").cumcount() * 5 / 1000
        )

        # This has to happen AFTER alignment between photometry and behavior because first ENL triggers sync pulse
        _split_penalty_states(timeseries_task_states_df, behavior_df, penalty="ENLP")
        _split_penalty_states(timeseries_task_states_df, behavior_df, penalty="CueP")

        n_bins, remainder = divmod(
            len(timeseries_task_states_df), downsample_factor
        )  # get number of bins to downsample into
        bin_ids = [
            j for i in range(int(n_bins)) for j in np.repeat(i, downsample_factor)
        ]  # define ids of bins at downsampling rate [1,1,1,1,2,2,2,2,...]
        bin_ids.extend(
            np.repeat(bin_ids[-1] + 1, remainder)
        )  # tag on incomplete bin at end
        timeseries_task_states_df[
            "bin_ids"
        ] = bin_ids  # new column to label new bin_ids

        downsampled_states_df: pd.DataFrame = deepcopy(timeseries_task_states_df)

        # Apply aggregate function to each column
        col_fcns = {
            col: np.max
            for col in downsampled_states_df.columns
            if col not in photo_columns
        }
        [col_fcns.update({col: np.mean}) for col in photo_columns]

        # Handle penalties. Label preceding states as different from those without penalties
        downsampled_states_df = downsampled_states_df.groupby("bin_ids").agg(col_fcns)
        downsampled_states_df = downsampled_states_df.reset_index(drop=True)
        downsampled_states_df = downsampled_states_df.drop(columns=["bin_ids"])

        # Get new
        trace_names = list(downsampled_states_df.columns[-6:])
        # Populate FiberPhotometrySynced
        self.insert1(
            {
                **key,
                "timestamps": downsampled_states_df["session_clock"].values,
                "time_offset": time_offset,
                "sample_rate": target_downsample_rate,
            }
        )

        # Populate FiberPhotometry
        synced_trace_list: list[dict] = []

        for trace_name in trace_names:

            synced_trace_list.append(
                {
                    **key,
                    "fiber_id": get_fiber_id(trace_name[-1]),
                    "hemisphere": {"R": "right", "L": "left"}[trace_name[-1]],
                    "trace_name": trace_name.split("_")[0],
                    "emission_color": get_color(trace_name.split("_")[1][0]),
                    "trace": downsampled_states_df[trace_name].values,
                }
            )

        self.SyncedTrace.insert(synced_trace_list)

def _split_penalty_states(
    df: pd.DataFrame, behavior_df: pd.DataFrame, penalty: str = "ENLP"
) -> None:
    """Handle penalties. Label preceding states as different from those without penalties"""
    penalty_trials = df.loc[df[penalty] == 1].nTrial.unique()

    if len(penalty_trials) > 1:
        penalty_groups = df.loc[df.nTrial.isin(penalty_trials)].groupby(
            "nTrial", as_index=False
        )

        mask = penalty_groups.apply(
            lambda x: x[f"n{penalty[:-1]}"]
            < behavior_df.loc[behavior_df.nTrial == x.nTrial.iloc[0].squeeze()][
                f"n_{penalty[:-1]}"
            ].squeeze()
        )

    else:
        mask = (
            df.loc[df.nTrial.isin(penalty_trials), f"n{penalty[:-1]}"]
            < behavior_df.loc[behavior_df.nTrial.isin(penalty_trials)][
                f"n_{penalty[:-1]}"
            ].squeeze()
        )

    # Label pre-penalty states as penalties
    df[f"state_{penalty}"] = 0
    df.loc[df.nTrial.isin(penalty_trials), f"state_{penalty}"] = (
        mask.values * df.loc[df.nTrial.isin(penalty_trials), f"{penalty[:-1]}"]
    )

    # Remove pre-penalty states from true states
    df.loc[df.nTrial.isin(penalty_trials), f"{penalty[:-1]}"] = (
        1 - mask.values
    ) * df.loc[df.nTrial.isin(penalty_trials), f"{penalty[:-1]}"]
