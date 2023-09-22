#!/usr/bin/env python
"""
EODataDown - a sensor class for Landsat8 C2L2 data downloaded from the Earth Explorer.
"""
# This file is part of 'EODataDown'
# A tool for automating Earth Observation Data Downloading.
#
# Copyright 2018 Pete Bunting
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
#
# Purpose:  Provides a sensor class for Landsat8 C2L2 data downloaded from the Earth Explorer.
#
# Author: Carole Planque
# Email: cap33@aber.ac.uk
# Date: 29/06/2022
# Version: 1.0
#
# History:
# Version 1.0 - Created.

import logging
import json
import os
import sys
import datetime
import multiprocessing
import shutil
import rsgislib
import uuid
import yaml
import subprocess
import importlib
import traceback

from osgeo import osr
from osgeo import ogr
from osgeo import gdal

import eodatadown.eodatadownutils
from eodatadown.eodatadownutils import EODataDownException
from eodatadown.eodatadownsensor import EODataDownSensor
from eodatadown.eodatadownusagedb import EODataDownUpdateUsageLogDB
import eodatadown.eodatadownrunarcsi

from sqlalchemy.ext.declarative import declarative_base
import sqlalchemy
import sqlalchemy.types
import sqlalchemy.dialects.postgresql
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.sql.expression import func

### added libraries
import ee_m2m
from datetime import date
import tarfile
import glob

logger = logging.getLogger(__name__)

Base = declarative_base()


class EDDLandsat8EE(Base):
    __tablename__ = "EDDLandsat8EE"

    PID = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    Scene_ID = sqlalchemy.Column(sqlalchemy.String, nullable=False) 
    Product_ID = sqlalchemy.Column(sqlalchemy.String, nullable=True)
    Spacecraft_ID = sqlalchemy.Column(sqlalchemy.String, nullable=True)
    Sensor_ID = sqlalchemy.Column(sqlalchemy.String, nullable=True)
    Date_Acquired = sqlalchemy.Column(sqlalchemy.Date, nullable=True)
    Collection_Number = sqlalchemy.Column(sqlalchemy.String, nullable=True)
    Collection_Category = sqlalchemy.Column(sqlalchemy.String, nullable=True)
    Sensing_Time = sqlalchemy.Column(sqlalchemy.DateTime, nullable=True)
    Data_Type = sqlalchemy.Column(sqlalchemy.String, nullable=True)
    WRS_Path = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)
    WRS_Row = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)
    Cloud_Cover = sqlalchemy.Column(sqlalchemy.Float, nullable=False, default=0.0)
    North_Lat = sqlalchemy.Column(sqlalchemy.Float, nullable=False)
    South_Lat = sqlalchemy.Column(sqlalchemy.Float, nullable=False)
    East_Lon = sqlalchemy.Column(sqlalchemy.Float, nullable=False)
    West_Lon = sqlalchemy.Column(sqlalchemy.Float, nullable=False)
    Total_Size = sqlalchemy.Column(sqlalchemy.Integer, nullable=True)
    Remote_URL = sqlalchemy.Column(sqlalchemy.String, nullable=False)
    Query_Date = sqlalchemy.Column(sqlalchemy.DateTime, nullable=False)
    Download_Start_Date = sqlalchemy.Column(sqlalchemy.DateTime, nullable=True)
    Download_End_Date = sqlalchemy.Column(sqlalchemy.DateTime, nullable=True)
    Downloaded = sqlalchemy.Column(sqlalchemy.Boolean, nullable=False, default=False)
    Download_Path = sqlalchemy.Column(sqlalchemy.String, nullable=False, default="")
    Archived = sqlalchemy.Column(sqlalchemy.Boolean, nullable=False, default=False)
    ARDProduct_Start_Date = sqlalchemy.Column(sqlalchemy.DateTime, nullable=True)
    ARDProduct_End_Date = sqlalchemy.Column(sqlalchemy.DateTime, nullable=True)
    ARDProduct = sqlalchemy.Column(sqlalchemy.Boolean, nullable=False, default=False)
    ARDProduct_Path = sqlalchemy.Column(sqlalchemy.String, nullable=False, default="")
    DCLoaded_Start_Date = sqlalchemy.Column(sqlalchemy.DateTime, nullable=True)
    DCLoaded_End_Date = sqlalchemy.Column(sqlalchemy.DateTime, nullable=True)
    DCLoaded = sqlalchemy.Column(sqlalchemy.Boolean, nullable=False, default=False)
    Invalid = sqlalchemy.Column(sqlalchemy.Boolean, nullable=False, default=False)
    ExtendedInfo = sqlalchemy.Column(sqlalchemy.dialects.postgresql.JSONB, nullable=True)
    RegCheck = sqlalchemy.Column(sqlalchemy.Boolean, nullable=False, default=False)


class EDDLandsat8EEPlugins(Base):
    __tablename__ = "EDDLandsat8EEPlugins"
    Scene_PID = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
    PlugInName = sqlalchemy.Column(sqlalchemy.String, primary_key=True)
    Start_Date = sqlalchemy.Column(sqlalchemy.DateTime, nullable=True)
    End_Date = sqlalchemy.Column(sqlalchemy.DateTime, nullable=True)
    Completed = sqlalchemy.Column(sqlalchemy.Boolean, nullable=False, default=False)
    Success = sqlalchemy.Column(sqlalchemy.Boolean, nullable=False, default=False)
    Outputs = sqlalchemy.Column(sqlalchemy.Boolean, nullable=False, default=False)
    Error = sqlalchemy.Column(sqlalchemy.Boolean, nullable=False, default=False)
    ExtendedInfo = sqlalchemy.Column(sqlalchemy.dialects.postgresql.JSONB, nullable=True)


def _untarFile(path, product_id, output_dir):
    scene_path = os.path.join(path, product_id+".tar")
    tarFile = tarfile.open(scene_path)
    tarFile.extractall(output_dir)
    tarFile.close()


def _deleteFiles(path, pattern):
    patternPath = os.path.join(path, pattern)
    for File in glob.glob(patternPath):
        os.remove(File)


def _renameBands(sceneDir):
    os.rename(glob.glob(os.path.join(sceneDir,"*SR_B1.TIF"))[0], os.path.join(sceneDir,"B01_tmp.tif"))
    os.rename(glob.glob(os.path.join(sceneDir,"*SR_B2.TIF"))[0], os.path.join(sceneDir,"B02_tmp.tif"))
    os.rename(glob.glob(os.path.join(sceneDir,"*SR_B3.TIF"))[0], os.path.join(sceneDir,"B03_tmp.tif"))
    os.rename(glob.glob(os.path.join(sceneDir,"*SR_B4.TIF"))[0], os.path.join(sceneDir,"B04_tmp.tif"))
    os.rename(glob.glob(os.path.join(sceneDir,"*SR_B5.TIF"))[0], os.path.join(sceneDir,"B05_tmp.tif"))
    os.rename(glob.glob(os.path.join(sceneDir,"*SR_B6.TIF"))[0], os.path.join(sceneDir,"B06_tmp.tif"))
    os.rename(glob.glob(os.path.join(sceneDir,"*SR_B7.TIF"))[0], os.path.join(sceneDir,"B07_tmp.tif"))
    os.rename(glob.glob(os.path.join(sceneDir,"*QA_PIXEL.TIF"))[0], os.path.join(sceneDir,"QA_PIXEL_tmp.tif"))
    os.rename(glob.glob(os.path.join(sceneDir,"*QA_RADSAT.TIF"))[0], os.path.join(sceneDir,"QA_RADSAT_tmp.tif"))
    os.rename(glob.glob(os.path.join(sceneDir,"*QA_AEROSOL.TIF"))[0], os.path.join(sceneDir,"QA_AEROSOL_tmp.tif"))
    
    for File in glob.glob(os.path.join(sceneDir,"*_L2SP_*")):
        os.rename(File, os.path.join(sceneDir,File.split('_')[-1]))


def _set_nodata_value(in_file, nodata_value):
    """
    Sets nodata value for all bands of a GDAL dataset.
    Arguments:
    * in_file - path to existing GDAL dataset.
    * nodata_value - nodata value
    """

    gdal_ds = gdal.Open(in_file, gdal.GA_Update)

    for i in range(gdal_ds.RasterCount):
        gdal_ds.GetRasterBand(i+1).SetNoDataValue(nodata_value)

    gdal_ds = None


def _reproject_file_to_cog(in_file, out_file, proj_wkt_file):
    """
    Reproject a file to a cloud optimised geotiff (COG)
    For compatability with older versions of GDAL set creation options rather than specifying 'COG'
    """
    with open(proj_wkt_file) as f:
        proj_wkt = f.read()

    in_ds = gdal.Open(in_file, gdal.GA_ReadOnly)
    x_src_res = in_ds.GetGeoTransform()[1]
    y_src_res = in_ds.GetGeoTransform()[5]
    gdal.Warp(out_file, in_ds, format="GTiff",
              xRes=x_src_res, yRes=y_src_res,
              dstSRS=proj_wkt, multithread=False,
              creationOptions=["COMPRESS=LZW", "TILED=YES"])
    in_ds = None

def _create_vrt_stack(scenedir):
    """
    Create a VRT stack for Landsat8 C2 L2 data for further processing.
    """
    out_vrt = os.path.join(scenedir, "{}_stack.vrt".format(os.path.basename(scenedir)))

    gdalvrd_cmd = ["gdalbuildvrt", "-separate", "-o", out_vrt,
                   os.path.join(scenedir, "B01.tif"),
                   os.path.join(scenedir, "B02.tif"),
                   os.path.join(scenedir, "B03.tif"),
                   os.path.join(scenedir, "B04.tif"),
                   os.path.join(scenedir, "B05.tif"),
                   os.path.join(scenedir, "B06.tif"),
                   os.path.join(scenedir, "B07.tif")]
    subprocess.call(gdalvrd_cmd)

    if os.path.isfile(out_vrt):
        _set_nodata_value(out_vrt, 0)


def _download_scn_ee(params):
    """
    Function which is used for downloading landsat8 data from EE platform.
    :param params:
    :return:
    """
    pid = params[0]
    scn_id = params[1]
    db_info_obj = params[2]
    scn_remote_url = params[3]
    scn_lcl_dwnld_path = params[4]

    download_completed = False
    logger.info("Downloading from EE" + scn_id)
    start_date = datetime.datetime.now()
    ee_m2m.runDownload(scn_remote_url, scn_lcl_dwnld_path)
    end_date = datetime.datetime.now()
    download_completed = True    
    logger.info("Finished Downloading " + scn_id)

    if download_completed:
        logger.debug("Set up database connection and update record.")
        db_engine = sqlalchemy.create_engine(db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()
        query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.PID == pid).one_or_none()
        if query_result is None:
            logger.error("Could not find the scene within local database: PID = {}".format(pid))
            ses.commit()
            ses.close()
            raise EODataDownException("Could not find the scene within local database: PID = {}".format(pid))

        query_result.Downloaded = True
        query_result.Download_Start_Date = start_date
        query_result.Download_End_Date = end_date
        query_result.Download_Path = scn_lcl_dwnld_path
        ses.commit()
        ses.close()
        logger.debug("Finished download and updated database.")
    else:
        logger.error("Download did not complete, re-run and it should continue from where it left off: {}".format(scn_lcl_dwnld_path))
    

def _post_process_usgs_l2sp_scene(scene_path, prod_id, output_dir, proj_wkt_file):
    """
    Takes an USGS C2 L2 scene and reprojects files, saving as GeoTiffs
    """
    
    if (os.path.isdir(output_dir)!=True) | (len(os.listdir(output_dir)) == 0):
        print("Untaring {}.tar ...".format(prod_id))
        _untarFile(scene_path, prod_id, output_dir)
        #Delete thermal files
        _deleteFiles(output_dir, "*_ST_*")
        #Rename bands for DC indexing
        _renameBands(output_dir)
        #Reproject to OSGB 
        for Band in glob.glob(os.path.join(output_dir,"*_tmp.tif")):
            bandName = Band.split("_tmp",2)[0]
            out_tif = bandName + ".tif"
            if out_tif in glob.glob(os.path.join(output_dir,"*.tif")):
                print("Band ({}) already re-projected.".format(bandName.split("/")[-1]))
            else:
                print("Converting {} to OSGB COG ...".format(bandName.split("/")[-1]))
                _reproject_file_to_cog(Band, out_tif, proj_wkt_file)
        
        #Delete temporary files 
        _deleteFiles( output_dir, "*_tmp.tif")
    
    else:
        print("{} already in ARD format ...".format(prod_id))

    _create_vrt_stack(output_dir)

    if len(glob.glob(os.path.join(output_dir, "*_stack.vrt"))) == 1:
        return True
    else:
        logger.error("Failed to post-process {}".format(prod_id))
        return False


def _process_to_ard(params):
    """
    A function which is used with the python multiprocessing pool feature to convert a scene to an ARD product
    using multiple processing cores.
    :param params:
    :return:
    """
    pid = params[0]
    scn_id = params[1]
    db_info_obj = params[2]
    scn_path = params[3]
    dem_file = params[4]
    output_dir = params[5]
    tmp_dir = params[6]
    spacecraft_str = params[7]
    sensor_str = params[8]
    final_ard_path = params[9]
    reproj_outputs = params[10]
    proj_wkt_file = params[11]
    projabbv = params[12]
    use_roi = params[13]
    intersect_vec_file = params[14]
    intersect_vec_lyr = params[15]
    subset_vec_file = params[16]
    subset_vec_lyr = params[17]
    mask_outputs = params[18]
    mask_vec_file = params[19]
    mask_vec_lyr = params[20]
    ard_method = params[21]
    product_id = params[22]
    
    edd_utils = eodatadown.eodatadownutils.EODataDownUtils()
    start_date = datetime.datetime.now()
    
    
    if ard_method == "ARCSI":
        input_mtl = edd_utils.findFirstFile(scn_path, "*MTL.txt")

        eodatadown.eodatadownrunarcsi.run_arcsi_landsat(input_mtl, dem_file, output_dir, tmp_dir, spacecraft_str,
                                                        sensor_str, reproj_outputs, proj_wkt_file, projabbv)

        logger.debug("Move final ARD files to specified location.")
        # Move ARD files to be kept.
        valid_output = eodatadown.eodatadownrunarcsi.move_arcsi_stdsref_products(output_dir, final_ard_path, use_roi,
                                                                                 intersect_vec_file, intersect_vec_lyr,
                                                                                 subset_vec_file, subset_vec_lyr,
                                                                                 mask_outputs, mask_vec_file, mask_vec_lyr,
                                                                                 tmp_dir)
        # Remove Remaining files.
        shutil.rmtree(output_dir)
        shutil.rmtree(tmp_dir)
        logger.debug("Moved final ARD files to specified location.")
    
    
    elif ard_method == "USGS_L2SP":
        valid_output = _post_process_usgs_l2sp_scene(scn_path, product_id, final_ard_path, proj_wkt_file)
        
    end_date = datetime.datetime.now()
    
    
    if valid_output:
        logger.debug("Set up database connection and update record.")
        db_engine = sqlalchemy.create_engine(db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()
        query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Scene_ID == scn_id).one_or_none()
        if query_result is None:
            logger.error("Could not find the scene within local database: " + scn_id)
        query_result.ARDProduct = True
        query_result.ARDProduct_Start_Date = start_date
        query_result.ARDProduct_End_Date = end_date
        query_result.ARDProduct_Path = final_ard_path
        ses.commit()
        ses.close()
        logger.debug("Finished download and updated database - scene valid.")
    else:
        logger.debug("Scene is not valid (e.g., too much cloud cover).")
        logger.debug("Set up database connection and update record.")
        db_engine = sqlalchemy.create_engine(db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()
        query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Scene_ID == scn_id).one_or_none()
        if query_result is None:
            logger.error("Could not find the scene within local database: " + scn_id)
        query_result.Invalid = True
        ses.commit()
        ses.close()
        logger.debug("Finished download and updated database - scene not valid.")


class EODataDownLandsat8EESensor (EODataDownSensor):
    """
    An class which represents the Landsat8 sensor being downloaded from the EarthExplorer.
    """

    def __init__(self, db_info_obj):
        """
        Function to initial the sensor.
        :param db_info_obj: Instance of a EODataDownDatabaseInfo object
        """
        EODataDownSensor.__init__(self, db_info_obj)
        self.sensor_name = "Landsat8EE"
        self.db_tab_name = "EDDLandsat8EE"
        self.ardMethod = "USGS_L2SP"

        self.use_roi = False
        self.intersect_vec_file = ''
        self.intersect_vec_lyr = ''
        self.subset_vec_file = ''
        self.subset_vec_lyr = ''
        self.mask_outputs = False
        self.mask_vec_file = ''
        self.mask_vec_lyr = ''
        self.std_vis_img_stch = None
        self.monthsOfInterest = None

    def parse_sensor_config(self, config_file, first_parse=False):
        """
        Parse the JSON configuration file. If first_parse=True then a signature file will be created
        which will be checked each time the system runs to ensure changes are not back to the
        configuration file. If the signature does not match the input file then an expection will be
        thrown. To update the configuration (e.g., extent date range or spatial area) run with first_parse=True.
        :param config_file: string with the path to the JSON file.
        :param first_parse: boolean as to whether the file has been previously parsed.
        """
        edd_file_checker = eodatadown.eodatadownutils.EDDCheckFileHash()
        # If it is the first time the config_file is parsed then create the signature file.
        if first_parse:
            edd_file_checker.createFileSig(config_file)
            logger.debug("Created signature file for config file.")

        if not edd_file_checker.checkFileSig(config_file):
            raise EODataDownException("Input config did not match the file signature.")

        with open(config_file) as f:
            config_data = json.load(f)
            json_parse_helper = eodatadown.eodatadownutils.EDDJSONParseHelper()
            logger.debug("Testing config file is for 'Landsat8EE'")
            json_parse_helper.getStrValue(config_data, ["eodatadown", "sensor", "name"], [self.sensor_name])
            logger.debug("Have the correct config file for 'Landsat8EE'")
            
            if json_parse_helper.doesPathExist(config_data,["eodatadown", "sensor", "ardparams", "software"]):
                self.ardMethod = json_parse_helper.getStrValue(config_data, ["eodatadown", "sensor", "ardparams", "software"],
                                                               valid_values=["ARCSI","USGS_L2SP"])
                logger.debug("Selected software from config file")

            logger.debug("Find ARD processing params from config file")
            self.demFile = json_parse_helper.getStrValue(config_data, ["eodatadown", "sensor", "ardparams", "dem"])
            self.projEPSG = -1
            self.projabbv = ""
            self.ardProjDefined = False
            if json_parse_helper.doesPathExist(config_data, ["eodatadown", "sensor", "ardparams", "proj"]):
                self.ardProjDefined = True
                self.projabbv = json_parse_helper.getStrValue(config_data,
                                                              ["eodatadown", "sensor", "ardparams", "proj", "projabbv"])
                self.projEPSG = int(json_parse_helper.getNumericValue(config_data,
                                                                      ["eodatadown", "sensor", "ardparams", "proj",
                                                                       "epsg"], 0, 1000000000))
            self.use_roi = False
            if json_parse_helper.doesPathExist(config_data, ["eodatadown", "sensor", "ardparams", "roi"]):
                self.use_roi = True
                self.intersect_vec_file = json_parse_helper.getStrValue(config_data,
                                                                        ["eodatadown", "sensor", "ardparams", "roi",
                                                                         "intersect", "vec_file"])
                self.intersect_vec_lyr = json_parse_helper.getStrValue(config_data,
                                                                       ["eodatadown", "sensor", "ardparams", "roi",
                                                                        "intersect", "vec_layer"])
                self.subset_vec_file = json_parse_helper.getStrValue(config_data,
                                                                     ["eodatadown", "sensor", "ardparams", "roi",
                                                                      "subset", "vec_file"])
                self.subset_vec_lyr = json_parse_helper.getStrValue(config_data,
                                                                    ["eodatadown", "sensor", "ardparams", "roi",
                                                                     "subset", "vec_layer"])
                self.mask_outputs = False
                if json_parse_helper.doesPathExist(config_data, ["eodatadown", "sensor", "ardparams", "roi", "mask"]):
                    self.mask_vec_file = json_parse_helper.getStrValue(config_data,
                                                                       ["eodatadown", "sensor", "ardparams", "roi",
                                                                        "mask", "vec_file"])
                    self.mask_vec_lyr = json_parse_helper.getStrValue(config_data,
                                                                      ["eodatadown", "sensor", "ardparams", "roi",
                                                                       "mask", "vec_layer"])

            if json_parse_helper.doesPathExist(config_data, ["eodatadown", "sensor", "ardparams", "visual"]):
                if json_parse_helper.doesPathExist(config_data,
                                                   ["eodatadown", "sensor", "ardparams", "visual", "stretch_file"]):
                    self.std_vis_img_stch = json_parse_helper.getStrValue(config_data, ["eodatadown", "sensor",
                                                                                        "ardparams", "visual",
                                                                                        "stretch_file"])

            logger.debug("Found ARD processing params from config file")

            logger.debug("Find paths from config file")
            if json_parse_helper.doesPathExist(config_data, ["eodatadown", "sensor", "paths"]):
                self.parse_output_paths_config(config_data["eodatadown"]["sensor"]["paths"])
            logger.debug("Found paths from config file")

            logger.debug("Find search params from config file")
            self.spacecraft = json_parse_helper.getStrValue(config_data,
                                                                   ["eodatadown", "sensor", "download", "spacecraft"],
                                                                   valid_values=["LANDSAT_8"])

            self.sensor = json_parse_helper.getStrValue(config_data,
                                                               ["eodatadown", "sensor", "download", "sensor"],
                                                               valid_values=["OLI_TIRS"])

            self.collectionLst = json_parse_helper.getStrListValue(config_data,
                                                                   ["eodatadown", "sensor", "download", "collection"],
                                                                   ["T1", "T2", "RT", "PRE"])

            self.cloudCoverThres = json_parse_helper.getNumericValue(config_data,
                                                                     ["eodatadown", "sensor", "download", "cloudcover"],
                                                                     0, 100)

            self.startDate = json_parse_helper.getDateValue(config_data,
                                                            ["eodatadown", "sensor", "download", "startdate"],
                                                            "%Y-%m-%d")
            
            if json_parse_helper.doesPathExist(config_data, ["eodatadown", "sensor", "download", "dataset"]):
                self.dataset = json_parse_helper.getStrValue(config_data,
                                                            ["eodatadown", "sensor", "download", "dataset"])

            if json_parse_helper.doesPathExist(config_data, ["eodatadown", "sensor", "download", "filetype"]):
                self.filetype = json_parse_helper.getStrValue(config_data,
                                                            ["eodatadown", "sensor", "download", "filetype"], 
                                                              valid_values=["band","bundle"])    
            
            if json_parse_helper.doesPathExist(config_data, ["eodatadown", "sensor", "download", "months"]):
                self.monthsOfInterest = json_parse_helper.getListValue(config_data,
                                                                       ["eodatadown", "sensor", "download", "months"])

            self.wrs2RowPaths = json_parse_helper.getListValue(config_data,
                                                               ["eodatadown", "sensor", "download", "wrs2"])
            for wrs2 in self.wrs2RowPaths:
                if (wrs2['path'] < 1) or (wrs2['path'] > 233):
                    logger.debug("Path error: " + str(wrs2))
                    raise EODataDownException("WRS2 paths must be between (including) 1 and 233.")
                if (wrs2['row'] < 1) or (wrs2['row'] > 248):
                    logger.debug("Row error: " + str(wrs2))
                    raise EODataDownException("WRS2 rows must be between (including) 1 and 248.")
            logger.debug("Found search params from config file")

            self.scn_intersect = False
            if json_parse_helper.doesPathExist(config_data, ["eodatadown", "sensor", "validity"]):
                logger.debug("Find scene validity params from config file")
                if json_parse_helper.doesPathExist(config_data, ["eodatadown", "sensor", "validity", "scn_intersect"]):
                    self.scn_intersect_vec_file = json_parse_helper.getStrValue(config_data,
                                                                                ["eodatadown", "sensor", "validity",
                                                                                 "scn_intersect", "vec_file"])
                    self.scn_intersect_vec_lyr = json_parse_helper.getStrValue(config_data,
                                                                               ["eodatadown", "sensor", "validity",
                                                                                "scn_intersect", "vec_lyr"])
                    self.scn_intersect = True
                logger.debug("Found scene validity params from config file")

            logger.debug("Find the plugins params")
            if json_parse_helper.doesPathExist(config_data, ["eodatadown", "sensor", "plugins"]):
                self.parse_plugins_config(config_data["eodatadown"]["sensor"]["plugins"])
            logger.debug("Found the plugins params")
            logger.debug("Find the EE APIkey params")
            if json_parse_helper.doesPathExist(config_data, ["eodatadown", "sensor", "m2minfo"]):
                self.service_url = json_parse_helper.getStrValue(config_data, ["eodatadown", "sensor", "m2minfo", 
                                                                               "service_url"])
                username = json_parse_helper.getStrValue(config_data, ["eodatadown", "sensor", "m2minfo", 
                                                                               "user", "username"])
                pwd = json_parse_helper.getStrValue(config_data, ["eodatadown", "sensor", "m2minfo", 
                                                                               "user", "password"])
                self.apiKey = ee_m2m.sendRequest(self.service_url + "login", {'username' : username, 'password' : pwd})
                
            logger.debug("Found the EE APIkey params")

    def init_sensor_db(self, drop_tables=True):
        """
        A function which initialises the database use the db_info_obj passed to __init__.
        Be careful as running this function drops the table if it already exists and therefore
        any data would be lost.
        """
        logger.debug("Creating Database Engine.")
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)

        if drop_tables:
            logger.debug("Drop system table if within the existing database.")
            Base.metadata.drop_all(db_engine)

        logger.debug("Creating Landsat8EE Database.")
        Base.metadata.bind = db_engine
        Base.metadata.create_all()

    def resolve_duplicated_scene_id(self, scn_id):
        """
        A function to resolve a duplicated scene ID within the database.
        :param scn_id:
        :return:
        """
        logger.debug("Creating Database Engine and Session.")
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()
        logger.debug("Find duplicate records for the scene_id: "+scn_id)
        query_rtn = ses.query(EDDLandsat8EE.PID, EDDLandsat8EE.Scene_ID, EDDLandsat8EE.Product_ID).\
            filter(EDDLandsat8EE.Scene_ID == scn_id).all()
        process_dates = list()
        for record in query_rtn:
            prod_id = record.Product_ID
            logger.debug("Record (Product ID): " + prod_id)
            if (prod_id is None) or (prod_id == ""):
                process_dates.append(None)
            prod_date = datetime.datetime.strptime(prod_id.split("_")[4], "%Y%m%d").date()
            process_dates.append(prod_date)

        curent_date = datetime.datetime.now().date()
        min_timedelta = None
        min_date_idx = 0
        idx = 0
        first = True
        for date_val in process_dates:
            if date_val is not None:
                c_timedelta = curent_date - date_val
                if first:
                    min_timedelta = c_timedelta
                    min_date_idx = idx
                    first = False
                elif c_timedelta < min_timedelta:
                    min_timedelta = c_timedelta
                    min_date_idx = idx
            idx = idx + 1
        logger.debug("Keeping (Product ID): " + query_rtn[min_date_idx].Product_ID)
        logger.debug("Deleting Remaining Products")
        ses.query(EDDLandsat8EE.PID, EDDLandsat8EE.Scene_ID, EDDLandsat8EE.Product_ID, ).\
            filter(EDDLandsat8EE.Scene_ID == scn_id).\
            filter(EDDLandsat8EE.Product_ID != query_rtn[min_date_idx].Product_ID).delete()
        ses.commit()
        ses.close()
        logger.debug("Completed processing of removing duplicate scene ids.")

    def check_new_scns(self, check_from_start=False):
        """
        Check whether there is new data available which is not within the existing database.
        Scenes not within the database will be added.
        """
        logger.info("Checking for new data... 'Landsat8EE'")
        
        logger.debug("Creating Database Engine and Session.")
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()

        logger.debug("Find the start date for query - if table is empty then using config date "
                     "otherwise date of last acquired image.")
        query_date = self.startDate

        if (not check_from_start) and (ses.query(EDDLandsat8EE).first() is not None):
            query_date = ses.query(EDDLandsat8EE).order_by(
                EDDLandsat8EE.Date_Acquired.desc()).first().Date_Acquired
        logger.info("Query with start at date: " + str(query_date))

        # Get the next PID value to ensure increment
        c_max_pid = ses.query(func.max(EDDLandsat8EE.PID).label("max_pid")).one().max_pid
        if c_max_pid is None:
            n_max_pid = 0
        else:
            n_max_pid = c_max_pid + 1
        
        # Search available scenes from EE using m2m 
        logger.debug("Perform EE query via Machine2Machine...")
        ee_filter_dataset_name = self.dataset
        ee_filter_maxcloud = int(self.cloudCoverThres)
        ee_filter_acquisition_start = query_date.strftime("%Y-%m-%d")
        ee_filter_acquisition_end = date.today().strftime("%Y-%m-%d")
        ee_service_url = self.service_url
        apiKey = self.apiKey
        filetype = self.filetype
        
        ee_filter_satellite_num = None
        if (self.spacecraft[-1] == "9") | (self.spacecraft[-1] == "8") | (
            self.spacecraft[-1] == "5") | (self.spacecraft[-1] == "4"):
            ee_filter_satellite_num = self.spacecraft[-1]
        
        month_filter = ''
        first = True
        if self.monthsOfInterest is not None:
            for curr_month in self.monthsOfInterest:
                sgn_month_filter = "(EXTRACT(MONTH FROM PARSE_DATETIME('%Y-%m-%d', date_acquired)) = {})".format(curr_month)
                if first:
                    month_filter = sgn_month_filter
                    first = False
                else:
                    month_filter = "{} OR {}".format(month_filter, sgn_month_filter)
            if month_filter != '':
                logger.info("Finding scenes for with month filter {}".format(month_filter))
                month_filter = "({})".format(month_filter)
        
        
        # Searching scenes in EE
        query_results = []
        for wrs2 in self.wrs2RowPaths: 
            ee_query = ee_m2m.ee_query(ee_filter_dataset_name, 
                                       ee_filter_acquisition_start, 
                                       ee_filter_acquisition_end, 
                                       ee_filter_maxcloud, 
                                       wrs2, 
                                       ee_filter_satellite_num)
            logger.info("Query: '{}' tile {}/{} from {} to {}".format(ee_filter_dataset_name,
                                                                   str(wrs2['path']),
                                                                   str(wrs2['row']),
                                                                   ee_filter_acquisition_start,
                                                                   ee_filter_acquisition_end))
            
            scn_search = ee_m2m.sendRequest(ee_service_url + "scene-search", ee_query, apiKey)
            for scn_result in scn_search["results"]:
                query_results.append(scn_result["entityId"])  
        
        logger.debug("Performed EE query")
        
        # Check if secne already in local database, if not : add it
        new_scns_avail = False
        if len(query_results) > 0:
            db_records = list()
            for scene_id in query_results:
                query_rtn = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Scene_ID == scene_id).all()
                if len(query_rtn) == 0:
                    # Get url and file size      
                    listId = f"temp_{ee_filter_dataset_name}_{scene_id}" 
                    dwnl_info = ee_m2m.get_download_details(listId, ee_filter_dataset_name, scene_id, filetype, 
                                                            ee_service_url, apiKey)
                    
                    # Get all other metadata required for adding scene to local database
                    scn_EErequest_metadata = ee_m2m.sendRequest(ee_service_url + "scene-metadata", {
                                                           "datasetName": ee_filter_dataset_name, 
                                                           "entityId": scene_id}, apiKey)
                    scn_metadata = ee_m2m.get_metadata(scn_EErequest_metadata)
                    
                    logger.debug("SceneID: " + scene_id + "\tProduct_ID: " + scn_metadata['product_id'])
                    
                    db_records.append(
                        EDDLandsat8EE(PID=n_max_pid, Scene_ID=scene_id, Product_ID=scn_metadata['product_id'],
                                         Spacecraft_ID=scn_metadata['spacecraft_id'],
                                         Sensor_ID=scn_metadata['sensor_id'],
                                         Date_Acquired=scn_metadata['date_acquired'],
                                         Collection_Number=scn_metadata['collection_number'],
                                         Collection_Category=scn_metadata['collection_category'],
                                         Sensing_Time=scn_metadata['sensing_time'],
                                         Data_Type=scn_metadata['data_type'], 
                                         WRS_Path=scn_metadata['wrs_path'], WRS_Row=scn_metadata['wrs_row'],
                                         Cloud_Cover=scn_metadata['cloud_cover'], 
                                         North_Lat=scn_metadata['north_lat'], South_Lat=scn_metadata['south_lat'],
                                         East_Lon=scn_metadata['east_lon'], West_Lon=scn_metadata['west_lon'], 
                                         Total_Size=dwnl_info['filesize'],
                                         Remote_URL=dwnl_info['url'], Query_Date=datetime.datetime.now(),
                                         Download_Start_Date=None,
                                         Download_End_Date=None, Downloaded=False, Download_Path="",
                                         Archived=False, ARDProduct_Start_Date=None,
                                         ARDProduct_End_Date=None, ARDProduct=False, ARDProduct_Path="",
                                         DCLoaded_Start_Date=None, DCLoaded_End_Date=None, DCLoaded=False))
                    n_max_pid = n_max_pid + 1
            if len(db_records) > 0:
                ses.add_all(db_records)
                ses.commit()
                new_scns_avail = True
        logger.debug("Processed EE query result and added to local database")
        client = None

        logger.debug("Check for any duplicate scene ids which have been added to database and "
                     "only keep the one processed more recently")
        query_rtn = ses.query(sqlalchemy.func.count(EDDLandsat8EE.Scene_ID), EDDLandsat8EE.Scene_ID).group_by(
            EDDLandsat8EE.Scene_ID).all()
        for result in query_rtn:
            if result[0] > 1:
                self.resolve_duplicated_scene_id(result[1])
        logger.debug("Completed duplicate check/removal.")

        ses.close()
        logger.debug("Closed Database session")
        edd_usage_db = EODataDownUpdateUsageLogDB(self.db_info_obj)
        edd_usage_db.add_entry(description_val="Checked for availability of new scenes", sensor_val=self.sensor_name,
                               updated_lcl_db=True, scns_avail=new_scns_avail)

    def rm_scns_intersect(self, all_scns=False):
        """
        A function which checks whether the bounding box for the scene intersects with a specified
        vector layer. If the scene does not intersect then it is deleted from the database. By default
        this is only testing the scenes which have not been downloaded.

        :param all_scns: If True all the scenes in the database will be tested otherwise only the
                         scenes which have not been downloaded will be tested.

        """
        if self.scn_intersect:
            import rsgislib.vectorutils
            logger.debug("Creating Database Engine and Session.")
            db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
            session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
            ses = session_sqlalc()
            logger.debug("Perform query to find scenes which need downloading.")

            if all_scns:
                scns = ses.query(EDDLandsat8EE).order_by(EDDLandsat8EE.Date_Acquired.asc()).all()
            else:
                scns = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Downloaded == False).order_by(
                                                                  EDDLandsat8EE.Date_Acquired.asc()).all()

            if scns is not None:
                eodd_vec_utils = eodatadown.eodatadownutils.EODDVectorUtils()
                vec_idx, geom_lst = eodd_vec_utils.create_rtree_index(self.scn_intersect_vec_file, self.scn_intersect_vec_lyr)

                for scn in scns:
                    logger.debug("Check Scene '{}' to check for intersection".format(scn.PID))
                    rsgis_utils = rsgislib.RSGISPyUtils()
                    north_lat = scn.North_Lat
                    south_lat = scn.South_Lat
                    east_lon = scn.East_Lon
                    west_lon = scn.West_Lon
                    # (xMin, xMax, yMin, yMax)
                    scn_bbox = [west_lon, east_lon, south_lat, north_lat]

                    intersect_vec_epsg = rsgis_utils.getProjEPSGFromVec(self.scn_intersect_vec_file, self.scn_intersect_vec_lyr)
                    if intersect_vec_epsg != 4326:
                        scn_bbox = rsgis_utils.reprojBBOX_epsg(scn_bbox, 4326, intersect_vec_epsg)

                    has_scn_intersect = eodd_vec_utils.bboxIntersectsIndex(vec_idx, geom_lst, scn_bbox)
                    if not has_scn_intersect:
                        logger.info("Removing scene {} from Landsat as it does not intersect.".format(scn.PID))
                        ses.query(EDDLandsat8EE.PID).filter(EDDLandsat8EE.PID == scn.PID).delete()
                        ses.commit()
            ses.close()

    def get_scnlist_all(self):
        """
        A function which returns a list of the unique IDs for all the scenes within the database.

        :return: list of integers
        """
        logger.debug("Creating Database Engine and Session.")
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()
        logger.debug("Perform query to find scenes which need downloading.")
        query_result = ses.query(EDDLandsat8EE).order_by(EDDLandsat8EE.Date_Acquired.asc()).all()
        scns = list()
        if query_result is not None:
            for record in query_result:
                scns.append(record.PID)
        ses.close()
        logger.debug("Closed the database session.")
        return scns

    def get_scnlist_download(self):
        """
        A function which queries the database to retrieve a list of scenes which are within the
        database but have yet to be downloaded.
        :return: A list of unq_ids for the scenes. The list will be empty if there are no scenes to download.
        """
        logger.debug("Creating Database Engine and Session.")
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()

        logger.debug("Perform query to find scenes which need downloading.")
        query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Downloaded == False).order_by(
                                                          EDDLandsat8EE.Date_Acquired.asc()).all()

        scns2dwnld = list()
        if query_result is not None:
            for record in query_result:
                scns2dwnld.append(record.PID)
        ses.close()
        logger.debug("Closed the database session.")
        return scns2dwnld

    def has_scn_download(self, unq_id):
        """
        A function which checks whether an individual scene has been downloaded.
        :param unq_id: the unique ID of the scene.
        :return: boolean (True for downloaded; False for not downloaded)
        """
        logger.debug("Creating Database Engine and Session.")
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()
        logger.debug("Perform query to find scene.")
        query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.PID == unq_id).one()
        ses.close()
        logger.debug("Closed the database session.")
        return query_result.Downloaded

    def download_scn(self, unq_id):
        """
        A function which downloads an individual scene and updates the database if download is successful.
        :param unq_id: the unique ID of the scene to be downloaded.
        :return: returns boolean indicating successful or otherwise download.
        """
        if not os.path.exists(self.baseDownloadPath):
            raise EODataDownException("The download path does not exist, please create and run again.")

        logger.debug("Creating Database Engine and Session.")
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()

        logger.debug("Perform query to find scene.")
        query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.PID == unq_id,
                                                          EDDLandsat8EE.Downloaded == False).all()
        ses.close()
        success = False
        if query_result is not None:
            if len(query_result) == 1:
                record = query_result[0]
                logger.debug("Retrieving url for PID '{}'".format(record.PID))
                logger.debug("Retrieved url '{}'".format(record.Remote_URL))
                
                _download_scn_ee([record.PID, record.Scene_ID, self.db_info_obj, 
                                  record.Remote_URL, self.baseDownloadPath])
                
                success = True
            elif len(query_result) == 0:
                logger.info("PID {0} is either not available or already been downloaded.".format(unq_id))
            else:
                logger.error("PID {0} has returned more than 1 scene - must be unique something really wrong.".
                             format(unq_id))
                raise EODataDownException("There was more than 1 scene which has been found - "
                                          "something has gone really wrong!")
        else:
            logger.error("PID {0} has not returned a scene - check inputs.".format(unq_id))
            raise EODataDownException("PID {0} has not returned a scene - check inputs.".format(unq_id))
        return success

    def download_all_avail(self, n_cores):
        """
        Queries the database to find all scenes which have not been downloaded and then downloads them.
        This function uses the python multiprocessing Pool to allow multiple simultaneous downloads to occur.
        Be careful not use more cores than your internet connection and server can handle.
        :param n_cores: The number of scenes to be simultaneously downloaded.
        """
        if not os.path.exists(self.baseDownloadPath):
            raise EODataDownException("The download path does not exist, please create and run again.")
        
        logger.debug("Creating Database Engine and Session.")
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()

        logger.debug("Perform query to find scenes which need downloading.")
        query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Downloaded == False).all()

        dwnld_params = list()
        if query_result is not None:
            logger.debug("Build download file list.")
            for record in query_result:
                logger.debug("Retrieving url for PID '{}'".format(record.PID))
                logger.debug("Retrieved url '{}'".format(record.Remote_URL))

                dwnld_params.append([record.PID, record.Scene_ID, self.db_info_obj, 
                                     record.Remote_URL, self.baseDownloadPath])
        else:
            logger.info("There are no scenes to be downloaded.")
        
        ses.close()
        logger.debug("Closed the database session.")

        logger.info("Start downloading the scenes.")
        with multiprocessing.Pool(processes=n_cores) as pool:
            pool.map(_download_scn_ee, dwnld_params)
        logger.info("Finished downloading the scenes.")
        edd_usage_db = EODataDownUpdateUsageLogDB(self.db_info_obj)
        edd_usage_db.add_entry(description_val="Checked downloaded new scenes.", sensor_val=self.sensor_name,
                               updated_lcl_db=True, downloaded_new_scns=True)

    def get_scnlist_con2ard(self):
        """
        A function which queries the database to find scenes which have been downloaded but have not yet been
        processed to an analysis ready data (ARD) format.
        :return: A list of unq_ids for the scenes. The list will be empty if there are no scenes to process.
        """
        logger.debug("Creating Database Engine and Session.")
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()

        logger.debug("Perform query to find scenes which need downloading.")
        query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Downloaded == True,
                                                          EDDLandsat8EE.ARDProduct == False,
                                                          EDDLandsat8EE.Invalid == False).order_by(
                                                          EDDLandsat8EE.Date_Acquired.asc()).all()

        scns2ard = list()
        if query_result is not None:
            for record in query_result:
                scns2ard.append(record.PID)
        ses.close()
        logger.debug("Closed the database session.")
        return scns2ard

    def has_scn_con2ard(self, unq_id):
        """
        A function which checks whether a scene has been converted to an ARD product.
        :param unq_id: the unique ID of the scene of interest.
        :return: boolean (True: has been converted. False: Has not been converted)
        """
        logger.debug("Creating Database Engine and Session.")
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()
        logger.debug("Perform query to find scene.")
        query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.PID == unq_id).one()
        ses.close()
        logger.debug("Closed the database session.")
        return (query_result.ARDProduct == True) and (query_result.Invalid == False)

    def scn2ard(self, unq_id):
        """
        A function which processes a single scene to an analysis ready data (ARD) format.
        :param unq_id: the unique ID of the scene to be processed.
        :return: returns boolean indicating successful or otherwise processing.
        """
        if not os.path.exists(self.ardFinalPath):
            raise EODataDownException("The ARD final path does not exist, please create and run again.")

        if not os.path.exists(self.ardProdWorkPath):
            raise EODataDownException("The ARD working path does not exist, please create and run again.")

        if not os.path.exists(self.ardProdTmpPath):
            raise EODataDownException("The ARD tmp path does not exist, please create and run again.")

        logger.debug("Creating Database Engine and Session.")
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()

        logger.debug("Perform query to find scene not ARD but downloaded")
        query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.PID == unq_id,
                                                          EDDLandsat8EE.Downloaded == True,
                                                          EDDLandsat8EE.ARDProduct == False).one_or_none()
        print("Perform query to find scene not ARD but downloaded")
        ses.close()

        proj_wkt_file = None
        if self.ardProjDefined:
            rsgis_utils = rsgislib.RSGISPyUtils()
            proj_wkt = rsgis_utils.getWKTFromEPSGCode(self.projEPSG)

        if query_result is not None:
            record = query_result
            logger.debug("Create the specific output directories for the ARD processing.")
            dt_obj = datetime.datetime.now()

            work_ard_path = os.path.join(self.ardProdWorkPath, dt_obj.strftime("%Y-%m-%d"))
            if not os.path.exists(work_ard_path):
                os.mkdir(work_ard_path)

            tmp_ard_path = os.path.join(self.ardProdTmpPath, dt_obj.strftime("%Y-%m-%d"))
            if not os.path.exists(tmp_ard_path):
                os.mkdir(tmp_ard_path)

            logger.debug("Create info for running ARD analysis for scene: " + record.Scene_ID)
            final_ard_scn_path = os.path.join(self.ardFinalPath, "{}".format(record.Product_ID, record.PID))
            if not os.path.exists(final_ard_scn_path):
                os.mkdir(final_ard_scn_path)

            work_ard_scn_path = os.path.join(work_ard_path, "{}_{}".format(record.Product_ID, record.PID))
            if not os.path.exists(work_ard_scn_path):
                os.mkdir(work_ard_scn_path)

            tmp_ard_scn_path = os.path.join(tmp_ard_path, "{}_{}".format(record.Product_ID, record.PID))
            if not os.path.exists(tmp_ard_scn_path):
                os.mkdir(tmp_ard_scn_path)

            if self.ardProjDefined:
                proj_wkt_file = os.path.join(work_ard_scn_path, record.Product_ID+"_wkt.wkt")
                rsgis_utils.writeList2File([proj_wkt], proj_wkt_file)

            _process_to_ard([record.PID, record.Scene_ID, self.db_info_obj, record.Download_Path, self.demFile,
                             work_ard_scn_path, tmp_ard_scn_path, record.Spacecraft_ID, record.Sensor_ID,
                             final_ard_scn_path, self.ardProjDefined, proj_wkt_file, self.projabbv, self.use_roi,
                             self.intersect_vec_file, self.intersect_vec_lyr, self.subset_vec_file, self.subset_vec_lyr,
                             self.mask_outputs, self.mask_vec_file, self.mask_vec_lyr, self.ardMethod, record.Product_ID])
        else:
            logger.error("PID {0} has not returned a scene - check inputs.".format(unq_id))
            raise EODataDownException("PID {0} has not returned a scene - check inputs.".format(unq_id))

    def scns2ard_all_avail(self, n_cores):
        """
        Queries the database to find all scenes which have been downloaded but not processed to an
        analysis ready data (ARD) format and then processed them to an ARD format.
        This function uses the python multiprocessing Pool to allow multiple simultaneous processing
        of the scenes using a single core for each scene.
        Be careful not use more cores than your system has or have I/O capacity for. The processing being
        undertaken is I/O heavy in the ARD Work and tmp paths. If you have high speed storage (e.g., SSD)
        available it is recommended the ARD work and tmp paths are located on this volume.
        :param n_cores: The number of scenes to be simultaneously processed.
        """
        if not os.path.exists(self.ardFinalPath):
            raise EODataDownException("The ARD final path does not exist, please create and run again.")

        if not os.path.exists(self.ardProdWorkPath):
            raise EODataDownException("The ARD working path does not exist, please create and run again.")

        if not os.path.exists(self.ardProdTmpPath):
            raise EODataDownException("The ARD tmp path does not exist, please create and run again.")

        logger.debug("Creating Database Engine and Session.")
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()
        logger.debug("Perform query to find scenes which need converting to ARD.")
        query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Downloaded == True,
                                                          EDDLandsat8EE.ARDProduct == False,
                                                          EDDLandsat8EE.Invalid == False).all()

        proj_wkt_file = None
        if self.ardProjDefined:
            rsgis_utils = rsgislib.RSGISPyUtils()
            proj_wkt = rsgis_utils.getWKTFromEPSGCode(self.projEPSG)

        ard_params = list()
        if query_result is not None:
            logger.debug("Create the specific output directories for the ARD processing.")
            dt_obj = datetime.datetime.now()

            work_ard_path = os.path.join(self.ardProdWorkPath, dt_obj.strftime("%Y-%m-%d"))
            if not os.path.exists(work_ard_path):
                os.mkdir(work_ard_path)

            tmp_ard_path = os.path.join(self.ardProdTmpPath, dt_obj.strftime("%Y-%m-%d"))
            if not os.path.exists(tmp_ard_path):
                os.mkdir(tmp_ard_path)

            for record in query_result:
                logger.debug("Create info for running ARD analysis for scene: {}".format(record.Product_ID))
                final_ard_scn_path = os.path.join(self.ardFinalPath, "{}_{}".format(record.Product_ID, record.PID))
                if not os.path.exists(final_ard_scn_path):
                    os.mkdir(final_ard_scn_path)

                work_ard_scn_path = os.path.join(work_ard_path, "{}_{}".format(record.Product_ID, record.PID))
                if not os.path.exists(work_ard_scn_path):
                    os.mkdir(work_ard_scn_path)

                tmp_ard_scn_path = os.path.join(tmp_ard_path, "{}_{}".format(record.Product_ID, record.PID))
                if not os.path.exists(tmp_ard_scn_path):
                    os.mkdir(tmp_ard_scn_path)

                if self.ardProjDefined:
                    proj_wkt_file = os.path.join(work_ard_scn_path, record.Product_ID+"_wkt.wkt")
                    rsgis_utils.writeList2File([proj_wkt], proj_wkt_file)

                ard_params.append([record.PID, record.Scene_ID, self.db_info_obj, record.Download_Path, self.demFile,
                                   work_ard_scn_path, tmp_ard_scn_path, record.Spacecraft_ID, record.Sensor_ID,
                                   final_ard_scn_path, self.ardProjDefined, proj_wkt_file, self.projabbv, self.use_roi,
                                   self.intersect_vec_file, self.intersect_vec_lyr, self.subset_vec_file, self.subset_vec_lyr,
                                   self.mask_outputs, self.mask_vec_file, self.mask_vec_lyr, self.ardMethod, record.Product_ID])
        else:
            logger.info("There are no scenes which have been downloaded but not processed to an ARD product.")
        ses.close()
        logger.debug("Closed the database session.")

        if len(ard_params) > 0:
            logger.info("Start processing the scenes.")
            with multiprocessing.Pool(processes=n_cores) as pool:
                pool.map(_process_to_ard, ard_params)
            logger.info("Finished processing the scenes.")

        edd_usage_db = EODataDownUpdateUsageLogDB(self.db_info_obj)
        edd_usage_db.add_entry(description_val="Processed scenes to an ARD product.", sensor_val=self.sensor_name,
                               updated_lcl_db=True, convert_scns_ard=True)

    def get_scnlist_datacube(self, loaded=False):
        """
        A function which queries the database to find scenes which have been processed to an ARD format
        but have not yet been loaded into the system datacube (specifed in the configuration file).
        :return: A list of unq_ids for the scenes. The list will be empty if there are no scenes to be loaded.
        """
        logger.debug("Creating Database Engine and Session.")
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()

        logger.debug("Perform query to find scenes which need converting to ARD.")
        query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.ARDProduct == True,
                                                          EDDLandsat8EE.DCLoaded == loaded).order_by(
                                                          EDDLandsat8EE.Date_Acquired.asc()).all()
        scns2dcload = list()
        if query_result is not None:
            for record in query_result:
                scns2dcload.append(record.PID)
        ses.close()
        logger.debug("Closed the database session.")
        return scns2dcload

    def has_scn_datacube(self, unq_id):
        """
        A function to find whether a scene has been loaded in the DataCube.
        :param unq_id: the unique ID of the scene.
        :return: boolean (True: Loaded in DataCube. False: Not loaded in DataCube)
        """
        logger.debug("Creating Database Engine and Session.")
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()
        logger.debug("Perform query to find scene.")
        query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.PID == unq_id).one()
        ses.close()
        logger.debug("Closed the database session.")
        return query_result.DCLoaded

    def scn2datacube(self, unq_id):
        """
        A function which loads a single scene into the datacube system.
        :param unq_id: the unique ID of the scene to be loaded.
        :return: returns boolean indicating successful or otherwise loading into the datacube.
        """
        # TODO ADD DataCube Functionality
        raise EODataDownException("Not implemented.")

    def scns2datacube_all_avail(self):
        """
        Queries the database to find all scenes which have been processed to an ARD format but not loaded
        into the datacube and then loads these scenes into the datacube.
        """
        rsgis_utils = rsgislib.RSGISPyUtils()

        datacube_cmd_path = 'datacube'
        datacube_cmd_path_env_value = os.getenv('DATACUBE_CMD_PATH', None)
        if datacube_cmd_path_env_value is not None:
            datacube_cmd_path = datacube_cmd_path_env_value

        logger.debug("Creating Database Engine and Session.")
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()

        logger.debug("Perform query to find scenes which need converting to ARD.")
        query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.ARDProduct == True,
                                                          EDDLandsat8EE.DCLoaded == False).all()

        if query_result is not None:
            logger.debug("Create the yaml files and load data into the datacube.")
            for record in query_result:
                start_date = datetime.datetime.now()
                scn_id = str(str(uuid.uuid5(uuid.NAMESPACE_URL, record.ARDProduct_Path)))
                print("{}: {}".format(record.Scene_ID, scn_id))
                img_file = rsgis_utils.findFile(record.ARDProduct_Path, '*vmsk_rad_srefdem_stdsref.tif')
                vmsk_img_file = rsgis_utils.findFile(record.ARDProduct_Path, '*_valid.tif')
                cmsk_img_file = rsgis_utils.findFile(record.ARDProduct_Path, '*_clouds.tif')
                yaml_file = os.path.splitext(img_file)[0]+"_yaml.yaml"
                epsg_code = rsgis_utils.getEPSGCode(img_file)
                lcl_proj_bbox = rsgis_utils.getImageBBOX(img_file)

                image_lyrs = dict()
                if record.Spacecraft_ID.upper() == "LANDSAT_8":
                    image_lyrs['coastal'] = {'layer': 1, 'path': img_file}
                    image_lyrs['blue'] = {'layer': 2, 'path': img_file}
                    image_lyrs['green'] = {'layer': 3, 'path': img_file}
                    image_lyrs['red'] = {'layer': 4, 'path': img_file}
                    image_lyrs['nir'] = {'layer': 5, 'path': img_file}
                    image_lyrs['swir1'] = {'layer': 6, 'path': img_file}
                    image_lyrs['swir2'] = {'layer': 7, 'path': img_file}
                    image_lyrs['fmask'] = {'layer': 1, 'path': cmsk_img_file}
                    image_lyrs['vmask'] = {'layer': 1, 'path': vmsk_img_file}
                else:
                    image_lyrs['blue'] = {'layer': 1, 'path': img_file}
                    image_lyrs['green'] = {'layer': 2, 'path': img_file}
                    image_lyrs['red'] = {'layer': 3, 'path': img_file}
                    image_lyrs['nir'] = {'layer': 4, 'path': img_file}
                    image_lyrs['swir1'] = {'layer': 5, 'path': img_file}
                    image_lyrs['swir2'] = {'layer': 6, 'path': img_file}
                    image_lyrs['fmask'] = {'layer': 1, 'path': cmsk_img_file}
                    image_lyrs['vmask'] = {'layer': 1, 'path': vmsk_img_file}

                scn_info = {
                    'id': scn_id,
                    'processing_level': 'LEVEL_2',
                    'product_type': 'ARCSI_SREF',
                    'creation_dt': record.ARDProduct_End_Date.strftime("%Y-%m-%d %H:%M:%S"),
                    'label': record.Scene_ID,
                    'platform': {'code': record.Spacecraft_ID.upper()},
                    'instrument': {'name': record.Sensor_ID.upper()},
                    'extent': {
                        'from_dt': record.Sensing_Time.strftime("%Y-%m-%d %H:%M:%S"),
                        'to_dt': record.Sensing_Time.strftime("%Y-%m-%d %H:%M:%S"),
                        'center_dt': record.Sensing_Time.strftime("%Y-%m-%d %H:%M:%S"),
                        'coord': {
                            'll': {'lat': record.South_Lat, 'lon': record.West_Lon},
                            'lr': {'lat': record.South_Lat, 'lon': record.East_Lon},
                            'ul': {'lat': record.North_Lat, 'lon': record.West_Lon},
                            'ur': {'lat': record.North_Lat, 'lon': record.East_Lon}
                        }
                    },
                    'format': {'name': 'GTIFF'},
                    'grid_spatial': {
                        'projection': {
                            'spatial_reference': 'EPSG:{}'.format(epsg_code),
                            'geo_ref_points': {
                                'll': {'x': lcl_proj_bbox[0], 'y': lcl_proj_bbox[2]},
                                'lr': {'x': lcl_proj_bbox[1], 'y': lcl_proj_bbox[2]},
                                'ul': {'x': lcl_proj_bbox[0], 'y': lcl_proj_bbox[3]},
                                'ur': {'x': lcl_proj_bbox[1], 'y': lcl_proj_bbox[3]}
                            }
                        }
                    },
                    'image': {'bands': image_lyrs},
                    'lineage': {'source_datasets': {}},
                }
                with open(yaml_file, 'w') as stream:
                    yaml.dump(scn_info, stream)

                cmd = "{0} dataset add {1}".format(datacube_cmd_path, yaml_file)
                try:
                    subprocess.call(cmd, shell=True)
                    # TODO Check that the dataset is really loaded - i.e., query datacube database
                    end_date = datetime.datetime.now()
                    record.DCLoaded_Start_Date = start_date
                    record.DCLoaded_End_Date = end_date
                    record.DCLoaded = True
                except Exception as e:
                    logger.debug("Failed to load scene: '{}'".format(cmd), exc_info=True)

        ses.commit()
        ses.close()
        logger.debug("Finished loading data into the datacube.")

    def get_scnlist_quicklook(self):
        """
        Get a list of all scenes which have not had a quicklook generated.

        :return: list of unique IDs
        """
        scns2quicklook = list()
        if self.calc_scn_quicklook():
            logger.debug("Creating Database Engine and Session.")
            db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
            session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
            ses = session_sqlalc()
            logger.debug("Perform query to find scene.")
            query_result = ses.query(EDDLandsat8EE).filter(
                sqlalchemy.or_(
                    EDDLandsat8EE.ExtendedInfo.is_(None),
                    sqlalchemy.not_(EDDLandsat8EE.ExtendedInfo.has_key('quicklook'))),
                EDDLandsat8EE.Invalid == False,
                EDDLandsat8EE.ARDProduct == True).order_by(
                            EDDLandsat8EE.Date_Acquired.asc()).all()
            if query_result is not None:
                for record in query_result:
                    scns2quicklook.append(record.PID)
            ses.close()
            logger.debug("Closed the database session.")
        return scns2quicklook

    def has_scn_quicklook(self, unq_id):
        """
        Check whether the quicklook has been generated for an individual scene.

        :param unq_id: integer unique ID for the scene.
        :return: boolean (True = has quicklook. False = has not got a quicklook)
        """
        logger.debug("Creating Database Engine and Session.")
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()
        logger.debug("Perform query to find scene.")
        query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.PID == unq_id).one()
        scn_json = query_result.ExtendedInfo
        ses.close()
        logger.debug("Closed the database session.")

        quicklook_calcd = False
        if scn_json is not None:
            json_parse_helper = eodatadown.eodatadownutils.EDDJSONParseHelper()
            quicklook_calcd = json_parse_helper.doesPathExist(scn_json, ["quicklook"])
        return quicklook_calcd

    def scn2quicklook(self, unq_id):
        """
        Generate the quicklook image for the scene.

        :param unq_id: integer unique ID for the scene.
        """
        if (self.quicklookPath is None) or (not os.path.exists(self.quicklookPath)):
            raise EODataDownException("The quicklook path does not exist or not provided, please create and run again.")

        if not os.path.exists(self.ardProdTmpPath):
            raise EODataDownException("The tmp path does not exist, please create and run again.")

        logger.debug("Creating Database Engine and Session.")
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()
        logger.debug("Perform query to find scene.")
        query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.PID == unq_id).one_or_none()
        if query_result is not None:
            if not query_result.ARDProduct:
                raise EODataDownException("Cannot create a quicklook as an ARD product has not been created.")
            if query_result.Invalid:
                raise EODataDownException("Cannot create a quicklook as image has been assigned as 'invalid'.")

            scn_json = query_result.ExtendedInfo
            if (scn_json is None) or (scn_json == ""):
                scn_json = dict()

            ard_img_path = query_result.ARDProduct_Path
            eodd_utils = eodatadown.eodatadownutils.EODataDownUtils()
            # Look for data which has been processed with ARCSI
            try:
                ard_img_file = eodd_utils.findFile(ard_img_path, '*vmsk_rad_srefdem_stdsref.tif')
            except:
                # Then check for L2 data downloaded from USGS with a VRT stack of all bands
                ard_img_file = eodd_utils.findFile(ard_img_path, '*_stack.vrt')
 
            out_quicklook_path = os.path.join(self.quicklookPath,
                                              "{}_{}".format(query_result.Product_ID, query_result.PID))
            if not os.path.exists(out_quicklook_path):
                os.mkdir(out_quicklook_path)

            tmp_quicklook_path = os.path.join(self.ardProdTmpPath,
                                              "quicklook_{}_{}".format(query_result.Product_ID, query_result.PID))
            if not os.path.exists(tmp_quicklook_path):
                os.mkdir(tmp_quicklook_path)

            # NIR, SWIR, RED
            bands = '4,5,3'
            if query_result.Spacecraft_ID.upper() == 'LANDSAT_8'.upper():
                bands = '5,6,4'

            ard_img_basename = os.path.splitext(os.path.basename(ard_img_file))[0]
            
            quicklook_imgs = list()
            quicklook_imgs.append(os.path.join(out_quicklook_path, "{}_250px.jpg".format(ard_img_basename)))
            quicklook_imgs.append(os.path.join(out_quicklook_path, "{}_1000px.jpg".format(ard_img_basename)))

            import rsgislib.tools.visualisation
            rsgislib.tools.visualisation.createQuicklookImgs(ard_img_file, bands, outputImgs=quicklook_imgs,
                                                             output_img_sizes=[250, 1000],  scale_axis='auto',
                                                             img_stats_msk=None, img_msk_vals=1,
                                                             stretch_file=self.std_vis_img_stch,
                                                             tmp_dir=tmp_quicklook_path)

            if not ("quicklook" in scn_json):
                scn_json["quicklook"] = dict()

            scn_json["quicklook"]["quicklookpath"] = out_quicklook_path
            scn_json["quicklook"]["quicklookimgs"] = quicklook_imgs
            query_result.ExtendedInfo = scn_json
            flag_modified(query_result, "ExtendedInfo")
            ses.add(query_result)
            ses.commit()
        else:
            raise EODataDownException("Could not find input image with PID {}".format(unq_id))
        ses.close()
        logger.debug("Closed the database session.")

    def scns2quicklook_all_avail(self):
        """
        Generate the quicklook images for the scenes for which a quicklook image do not exist.

        """
        scn_lst = self.get_scnlist_quicklook()
        for scn in scn_lst:
            self.scn2quicklook(scn)

    def get_scnlist_tilecache(self):
        """
        Get a list of all scenes for which a tile cache has not been generated.

        :return: list of unique IDs
        """
        scns2tilecache = list()
        if self.calc_scn_tilecache():
            logger.debug("Creating Database Engine and Session.")
            db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
            session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
            ses = session_sqlalc()
            logger.debug("Perform query to find scene.")
            query_result = ses.query(EDDLandsat8EE).filter(
                sqlalchemy.or_(
                    EDDLandsat8EE.ExtendedInfo.is_(None),
                    sqlalchemy.not_(EDDLandsat8EE.ExtendedInfo.has_key('tilecache'))),
                EDDLandsat8EE.Invalid == False,
                EDDLandsat8EE.ARDProduct == True).order_by(
                            EDDLandsat8EE.Date_Acquired.asc()).all()
            if query_result is not None:
                for record in query_result:
                    scns2tilecache.append(record.PID)
            ses.close()
            logger.debug("Closed the database session.")
        return scns2tilecache

    def has_scn_tilecache(self, unq_id):
        """
        Check whether a tile cache has been generated for an individual scene.

        :param unq_id: integer unique ID for the scene.
        :return: boolean (True = has tile cache. False = has not got a tile cache)
        """
        logger.debug("Creating Database Engine and Session.")
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()
        logger.debug("Perform query to find scene.")
        query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.PID == unq_id).one()
        scn_json = query_result.ExtendedInfo
        ses.close()
        logger.debug("Closed the database session.")

        tile_cache_calcd = False
        if scn_json is not None:
            json_parse_helper = eodatadown.eodatadownutils.EDDJSONParseHelper()
            tile_cache_calcd = json_parse_helper.doesPathExist(scn_json, ["tilecache"])
        return tile_cache_calcd

    def scn2tilecache(self, unq_id):
        """
        Generate the tile cache for the scene.

        :param unq_id: integer unique ID for the scene.
        """
        if (self.tilecachePath is None) or (not os.path.exists(self.tilecachePath)):
            raise EODataDownException("The tilecache path does not exist or not provided, please create and run again.")

        if not os.path.exists(self.ardProdTmpPath):
            raise EODataDownException("The tmp path does not exist, please create and run again.")

        logger.debug("Creating Database Engine and Session.")
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()
        logger.debug("Perform query to find scene.")
        query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.PID == unq_id).one_or_none()
        if query_result is not None:
            if not query_result.ARDProduct:
                raise EODataDownException("Cannot create a tilecache as an ARD product has not been created.")
            if query_result.Invalid:
                raise EODataDownException("Cannot create a tilecache as image has been assigned as 'invalid'.")

            scn_json = query_result.ExtendedInfo
            if (scn_json is None) or (scn_json == ""):
                scn_json = dict()

            ard_img_path = query_result.ARDProduct_Path
            eodd_utils = eodatadown.eodatadownutils.EODataDownUtils()
            # Look for data which has been processed with ARCSI
            try:
                ard_img_file = eodd_utils.findFile(ard_img_path, '*vmsk_rad_srefdem_stdsref.tif')
            except:
                # Then check for L2 data downloaded from USGS with a VRT stack of all bands
                ard_img_file = eodd_utils.findFile(ard_img_path, '*_stack.vrt')
 
            out_tilecache_dir = os.path.join(self.tilecachePath,
                                             "{}_{}".format(query_result.Product_ID, query_result.PID))
            if not os.path.exists(out_tilecache_dir):
                os.mkdir(out_tilecache_dir)

            out_visual_gtiff = os.path.join(out_tilecache_dir,
                                            "{}_{}_vis.tif".format(query_result.Product_ID, query_result.PID))

            tmp_tilecache_path = os.path.join(self.ardProdTmpPath,
                                            "tilecache_{}_{}".format(query_result.Product_ID, query_result.PID))
            if not os.path.exists(tmp_tilecache_path):
                os.mkdir(tmp_tilecache_path)

            # NIR, SWIR, RED
            bands = '4,5,3'
            if query_result.Spacecraft_ID.upper() == 'LANDSAT_8'.upper():
                bands = '5,6,4'

            import rsgislib.tools.visualisation
            rsgislib.tools.visualisation.createWebTilesVisGTIFFImg(ard_img_file, bands, out_tilecache_dir,
                                                                   out_visual_gtiff, zoomLevels='2-12',
                                                                   img_stats_msk=None, img_msk_vals=1,
                                                                   stretch_file=self.std_vis_img_stch,
                                                                   tmp_dir=tmp_tilecache_path, webview=True)

            if not ("tilecache" in scn_json):
                scn_json["tilecache"] = dict()
            scn_json["tilecache"]["tilecachepath"] = out_tilecache_dir
            scn_json["tilecache"]["visgtiff"] = out_visual_gtiff
            query_result.ExtendedInfo = scn_json
            flag_modified(query_result, "ExtendedInfo")
            ses.add(query_result)
            ses.commit()
        else:
            raise EODataDownException("Could not find input image with PID {}".format(unq_id))
        ses.close()
        logger.debug("Closed the database session.")
        shutil.rmtree(tmp_tilecache_path)

    def scns2tilecache_all_avail(self):
        """
        Generate the tile cache for the scenes for which a tile cache does not exist.
        """
        scn_lst = self.get_scnlist_tilecache()
        for scn in scn_lst:
            self.scn2tilecache(scn)

    def get_scn_record(self, unq_id):
        """
        A function which queries the database using the unique ID of a scene returning the record
        :param unq_id:
        :return: Returns the database record object
        """
        logger.debug("Creating Database Engine and Session.")
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()

        logger.debug("Perform query to find scene.")
        query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.PID == unq_id).all()
        ses.close()
        scn_record = None
        if query_result is not None:
            if len(query_result) == 1:
                scn_record = query_result[0]
            else:
                logger.error(
                    "PID {0} has returned more than 1 scene - must be unique something really wrong.".format(unq_id))
                raise EODataDownException(
                    "There was more than 1 scene which has been found - something has gone really wrong!")
        else:
            logger.error("PID {0} has not returned a scene - check inputs.".format(unq_id))
            raise EODataDownException("PID {0} has not returned a scene - check inputs.".format(unq_id))
        return scn_record

    def get_scn_obs_date(self, unq_id):
        """
        A function which returns a datetime object for the observation date/time of a scene.

        :param unq_id: the unique id (PID) of the scene of interest.
        :return: a datetime object.

        """
        import copy
        logger.debug("Creating Database Engine and Session.")
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()
        logger.debug("Perform query to find scene.")
        query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.PID == unq_id).all()
        ses.close()
        scn_record = None
        if query_result is not None:
            if len(query_result) == 1:
                scn_record = query_result[0]
            else:
                logger.error(
                      "PID {0} has returned more than 1 scene - must be unique something really wrong.".format(unq_id))
                raise EODataDownException(
                        "There was more than 1 scene which has been found - something has gone really wrong!")
        else:
            logger.error("PID {0} has not returned a scene - check inputs.".format(unq_id))
            raise EODataDownException("PID {0} has not returned a scene - check inputs.".format(unq_id))
        return copy.copy(scn_record.Sensing_Time)

    def get_scnlist_usr_analysis(self):
        """
        Get a list of all scenes for which user analysis needs to be undertaken.

        :return: list of unique IDs
        """
        scns2runusranalysis = list()
        if self.calc_scn_usr_analysis():
            logger.debug("Creating Database Engine and Session.")
            db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
            session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
            ses = session_sqlalc()

            usr_analysis_keys = self.get_usr_analysis_keys()

            query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Invalid == False,
                                                              EDDLandsat8EE.ARDProduct == True).order_by(
                                                              EDDLandsat8EE.Date_Acquired.asc()).all()

            for scn in query_result:
                scn_plgin_db_objs = ses.query(EDDLandsat8EEPlugins).filter(EDDLandsat8EEPlugins.Scene_PID == scn.PID).all()
                if (scn_plgin_db_objs is None) or (not scn_plgin_db_objs):
                    scns2runusranalysis.append(scn.PID)
                else:
                    for plugin_key in usr_analysis_keys:
                        plugin_completed = False
                        for plgin_db_obj in scn_plgin_db_objs:
                            if (plgin_db_obj.PlugInName == plugin_key) and plgin_db_obj.Completed:
                                plugin_completed = True
                                break
                        if not plugin_completed:
                            scns2runusranalysis.append(scn.PID)
                            break
            ses.close()
            logger.debug("Closed the database session.")
        return scns2runusranalysis

    def has_scn_usr_analysis(self, unq_id):
        usr_plugins_calcd = True
        logger.debug("Going to test whether there are plugins to execute.")
        if self.calc_scn_usr_analysis():
            logger.debug("Creating Database Engine and Session.")
            db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
            session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
            ses = session_sqlalc()
            logger.debug("Perform query to find scene.")
            query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.PID == unq_id).one_or_none()
            if query_result is None:
                raise EODataDownException("Scene ('{}') could not be found in database".format(unq_id))

            scn_plgin_db_objs = ses.query(EDDLandsat8EEPlugins).filter(EDDLandsat8EEPlugins.Scene_PID == unq_id).all()
            ses.close()
            logger.debug("Closed the database session.")
            if (scn_plgin_db_objs is None) or (not scn_plgin_db_objs):
                usr_plugins_calcd = False
            else:
                usr_analysis_keys = self.get_usr_analysis_keys()
                for plugin_key in usr_analysis_keys:
                    plugin_completed = False
                    for plgin_db_obj in scn_plgin_db_objs:
                        if (plgin_db_obj.PlugInName == plugin_key) and plgin_db_obj.Completed:
                            plugin_completed = True
                            break
                    if not plugin_completed:
                        usr_plugins_calcd = False
                        break
        return usr_plugins_calcd

    def run_usr_analysis(self, unq_id):
        if self.calc_scn_usr_analysis():
            for plugin_info in self.analysis_plugins:
                plugin_path = os.path.abspath(plugin_info["path"])
                plugin_module_name = plugin_info["module"]
                plugin_cls_name = plugin_info["class"]
                logger.debug("Using plugin '{}' from '{}'.".format(plugin_cls_name, plugin_module_name))

                # Check if plugin path input is already in system path.
                already_in_path = False
                for c_path in sys.path:
                    c_path = os.path.abspath(c_path)
                    if c_path == plugin_path:
                        already_in_path = True
                        break

                # Add plugin path to system path
                if not already_in_path:
                    sys.path.insert(0, plugin_path)
                    logger.debug("Add plugin path ('{}') to the system path.".format(plugin_path))

                # Try to import the module.
                logger.debug("Try to import the plugin module: '{}'".format(plugin_module_name))
                plugin_mod_inst = importlib.import_module(plugin_module_name)
                logger.debug("Imported the plugin module: '{}'".format(plugin_module_name))
                if plugin_mod_inst is None:
                    raise Exception("Could not load the module: '{}'".format(plugin_module_name))

                # Try to make instance of class.
                logger.debug("Try to create instance of class: '{}'".format(plugin_cls_name))
                plugin_cls_inst = getattr(plugin_mod_inst, plugin_cls_name)()
                logger.debug("Created instance of class: '{}'".format(plugin_cls_name))
                if plugin_cls_inst is None:
                    raise Exception("Could not create instance of '{}'".format(plugin_cls_name))
                plugin_key = plugin_cls_inst.get_ext_info_key()
                logger.debug("Using plugin '{}' from '{}' with key '{}'.".format(plugin_cls_name,
                                                                                 plugin_module_name,
                                                                                 plugin_key))

                # Try to read any plugin parameters to be passed to the plugin when instantiated.
                if "params" in plugin_info:
                    plugin_cls_inst.set_users_param(plugin_info["params"])
                    logger.debug("Read plugin params and passed to plugin.")

                logger.debug("Creating Database Engine and Session.")
                db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
                session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
                ses = session_sqlalc()
                logger.debug("Perform query to find scene.")
                scn_db_obj = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.PID == unq_id).one_or_none()
                if scn_db_obj is None:
                    raise EODataDownException("Scene ('{}') could not be found in database".format(unq_id))
                logger.debug("Perform query to find scene in plugin DB.")
                plgin_db_obj = ses.query(EDDLandsat8EEPlugins).filter(EDDLandsat8EEPlugins.Scene_PID == unq_id,
                                                                         EDDLandsat8EEPlugins.PlugInName == plugin_key).one_or_none()
                plgin_db_objs = ses.query(EDDLandsat8EEPlugins).filter(EDDLandsat8EEPlugins.Scene_PID == unq_id).all()
                ses.close()
                logger.debug("Closed the database session.")

                plgins_dict = dict()
                for plgin_obj in plgin_db_objs:
                    plgins_dict[plgin_obj.PlugInName] = plgin_obj

                plugin_completed = True
                exists_in_db = True
                if plgin_db_obj is None:
                    plugin_completed = False
                    exists_in_db = False
                elif not plgin_db_obj.Completed:
                    plugin_completed = False

                if not plugin_completed:
                    start_time = datetime.datetime.now()
                    try:
                        completed = True
                        error_occurred = False
                        plg_success, out_dict, plg_outputs = plugin_cls_inst.perform_analysis(scn_db_obj, self, plgins_dict)
                    except Exception as e:
                        plg_success = False
                        plg_outputs = False
                        error_occurred = True
                        out_dict = dict()
                        out_dict['error'] = str(e)
                        out_dict['traceback'] = traceback.format_exc()
                        completed = False
                    end_time = datetime.datetime.now()
                    if plg_success:
                        logger.debug("The plugin analysis has been completed - SUCCESSFULLY.")
                    else:
                        logger.debug("The plugin analysis has been completed - UNSUCCESSFULLY.")

                    if exists_in_db:
                        logger.debug("Creating Database Engine and Session.")
                        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
                        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
                        ses = session_sqlalc()
                        logger.debug("Perform query to find scene in plugin DB.")
                        plgin_db_obj = ses.query(EDDLandsat8EEPlugins).filter(
                            EDDLandsat8EEPlugins.Scene_PID == unq_id,
                            EDDLandsat8EEPlugins.PlugInName == plugin_key).one_or_none()

                        if plgin_db_obj is None:
                            raise EODataDownException("Do not know what has happened, scene plugin instance not found but was earlier.")

                        plgin_db_obj.Success = plg_success
                        plgin_db_obj.Completed = completed
                        plgin_db_obj.Outputs = plg_outputs
                        plgin_db_obj.Error = error_occurred
                        plgin_db_obj.Start_Date = start_time
                        plgin_db_obj.End_Date = end_time
                        if out_dict is not None:
                            plgin_db_obj.ExtendedInfo = out_dict
                            flag_modified(plgin_db_obj, "ExtendedInfo")
                        ses.add(plgin_db_obj)
                        ses.commit()
                        logger.debug("Committed updated record to database - PID {}.".format(unq_id))
                        ses.close()
                        logger.debug("Closed the database session.")
                    else:
                        plgin_db_obj = EDDLandsat8EEPlugins(Scene_PID=scn_db_obj.PID, PlugInName=plugin_key,
                                                               Start_Date=start_time, End_Date=end_time,
                                                               Completed=completed, Success=plg_success,
                                                               Error=error_occurred, Outputs=plg_outputs)
                        if out_dict is not None:
                            plgin_db_obj.ExtendedInfo = out_dict

                        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
                        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
                        ses = session_sqlalc()
                        ses.add(plgin_db_obj)
                        ses.commit()
                        logger.debug("Committed new record to database - PID {}.".format(unq_id))
                        ses.close()
                        logger.debug("Closed the database session.")
                else:
                    logger.debug("The plugin '{}' from '{}' has already been run so will not be run again".format(plugin_cls_name, plugin_module_name))

    def run_usr_analysis_all_avail(self, n_cores):
        scn_lst = self.get_scnlist_usr_analysis()
        for scn in scn_lst:
            self.run_usr_analysis(scn)

    def reset_usr_analysis(self, plgin_lst=None, scn_pid=None):
        """
        Reset the user analysis plugins within the database.

        :param plgin_lst: A list of plugins to be reset. If None (default) then all reset.
        :param scn_pid: Optionally specify the a scene PID, if provided then only that scene will be reset.
                        If None then all the scenes will be reset.

        """
        if self.calc_scn_usr_analysis():
            reset_all_plgins = False
            if plgin_lst is None:
                logger.debug(
                    "A list of plugins to reset has not been provided so populating that list with all plugins.")
                plgin_lst = self.get_usr_analysis_keys()
                reset_all_plgins = True
            logger.debug("There are {} plugins to reset".format(len(plgin_lst)))

            if len(plgin_lst) > 0:
                logger.debug("Creating Database Engine and Session.")
                db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
                session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
                ses = session_sqlalc()

                if scn_pid is None:
                    logger.debug("No scene PID has been provided so resetting all the scenes.")
                    for plgin_key in plgin_lst:
                        ses.query(EDDLandsat8EEPlugins).filter(EDDLandsat8EEPlugins.PlugInName == plgin_key).delete(synchronize_session=False)
                        ses.commit()
                else:
                    logger.debug("Scene PID {} has been provided so resetting.".format(scn_pid))
                    if reset_all_plgins:
                        ses.query(EDDLandsat8EEPlugins).filter(EDDLandsat8EEPlugins.Scene_PID == scn_pid).delete(synchronize_session=False)
                    else:
                        scn_plgin_db_objs = ses.query(EDDLandsat8EEPlugins).filter(EDDLandsat8EEPlugins.Scene_PID == scn_pid).all()
                        if (scn_plgin_db_objs is None) and (not scn_plgin_db_objs):
                            raise EODataDownException("Scene ('{}') could not be found in database".format(scn_pid))
                        for plgin_db_obj in scn_plgin_db_objs:
                            if plgin_db_obj.PlugInName in plgin_lst:
                                ses.delete(plgin_db_obj)
                    ses.commit()
                ses.close()

    def is_scn_invalid(self, unq_id):
        """
        A function which tests whether a scene has been defined as invalid.

        :param unq_id: the unique PID for the scene to test.
        :return: True: The scene is invalid. False: the Scene is valid.

        """
        logger.debug("Creating Database Engine and Session.")
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()
        logger.debug("Perform query to find scene.")
        query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.PID == unq_id).one_or_none()
        if query_result is None:
            raise EODataDownException("Scene ('{}') could not be found in database".format(unq_id))
        invalid = query_result.Invalid
        ses.close()
        logger.debug("Closed the database session.")
        return invalid

    def get_scn_unq_name(self, unq_id):
        """
        A function which returns a name which will be unique for the specified scene.

        :param unq_id: the unique PID for the scene.
        :return: string with a unique name.

        """
        logger.debug("Creating Database Engine and Session.")
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()
        logger.debug("Perform query to find scene.")
        query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.PID == unq_id).one_or_none()
        if query_result is None:
            raise EODataDownException("Scene ('{}') could not be found in database".format(unq_id))
        unq_name = "{}_{}".format(query_result.Product_ID, query_result.PID)
        ses.close()
        logger.debug("Closed the database session.")
        return unq_name

    def get_scn_unq_name_record(self, scn_record):
        """
        A function which returns a name which will be unique using the scene record object passed to the function.

        :param scn_record: the database dict like object representing the scene.
        :return: string with a unique name.

        """
        unq_name = "{}_{}".format(scn_record.Product_ID, scn_record.PID)
        return unq_name

    def find_unique_platforms(self):
        """
        A function which returns a list of unique platforms within the database (e.g., Landsat 5, Landsat 8).
        :return: list of strings.
        """
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()
        platforms = ses.query(EDDLandsat8EE.Spacecraft_ID).group_by(EDDLandsat8EE.Spacecraft_ID)
        ses.close()
        return platforms

    def query_scn_records_date_count(self, start_date, end_date, valid=True, cloud_thres=None):
        """
        A function which queries the database to find scenes within a specified date range
        and returns the number of records available.

        :param start_date: A python datetime object specifying the start date
        :param end_date: A python datetime object specifying the end date
        :param valid: If True only valid scene records will be returned (i.e., has been processed to an ARD product)
        :param cloud_thres: threshold for cloud cover. If None, then ignored.
        :return: count of records available
        """
        logger.debug("Creating Database Engine and Session.")
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()
        logger.debug("Perform query to find scene.")
        if cloud_thres is not None:
            if valid:
                n_rows = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Date_Acquired <= start_date,
                                                            EDDLandsat8EE.Date_Acquired >= end_date,
                                                            EDDLandsat8EE.Invalid == False,
                                                            EDDLandsat8EE.ARDProduct == True,
                                                            EDDLandsat8EE.Cloud_Cover <= cloud_thres).count()
            else:
                n_rows = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Date_Acquired <= start_date,
                                                            EDDLandsat8EE.Date_Acquired >= end_date,
                                                            EDDLandsat8EE.Cloud_Cover <= cloud_thres).count()
        else:
            if valid:
                n_rows = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Date_Acquired <= start_date,
                                                            EDDLandsat8EE.Date_Acquired >= end_date,
                                                            EDDLandsat8EE.Invalid == False,
                                                            EDDLandsat8EE.ARDProduct == True).count()
            else:
                n_rows = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Date_Acquired <= start_date,
                                                            EDDLandsat8EE.Date_Acquired >= end_date).count()
        ses.close()
        return n_rows

    def query_scn_records_date(self, start_date, end_date, start_rec=0, n_recs=0, valid=True, cloud_thres=None):
        """
        A function which queries the database to find scenes within a specified date range.
        The order of the records is descending (i.e., from current to historical)

        :param start_date: A python datetime object specifying the start date
        :param end_date: A python datetime object specifying the end date
        :param start_rec: A parameter specifying the start record, for example for pagination.
        :param n_recs: A parameter specifying the number of records to be returned.
        :param valid: If True only valid scene records will be returned (i.e., has been processed to an ARD product)
        :param cloud_thres: threshold for cloud cover. If None, then ignored.
        :return: list of database records
        """
        logger.debug("Creating Database Engine and Session.")
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()
        logger.debug("Perform query to find scene.")
        if cloud_thres is not None:
            if valid:
                if n_recs > 0:
                    query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Date_Acquired <= start_date,
                                                                      EDDLandsat8EE.Date_Acquired >= end_date,
                                                                      EDDLandsat8EE.Invalid == False,
                                                                      EDDLandsat8EE.ARDProduct == True,
                                                                      EDDLandsat8EE.Cloud_Cover <= cloud_thres).order_by(
                        EDDLandsat8EE.Date_Acquired.desc())[start_rec:(start_rec + n_recs)]
                else:
                    query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Date_Acquired <= start_date,
                                                                      EDDLandsat8EE.Date_Acquired >= end_date,
                                                                      EDDLandsat8EE.Invalid == False,
                                                                      EDDLandsat8EE.ARDProduct == True,
                                                                      EDDLandsat8EE.Cloud_Cover <= cloud_thres).order_by(
                        EDDLandsat8EE.Date_Acquired.desc()).all()
            else:
                if n_recs > 0:
                    query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Date_Acquired <= start_date,
                                                                      EDDLandsat8EE.Date_Acquired >= end_date,
                                                                      EDDLandsat8EE.Cloud_Cover <= cloud_thres).order_by(
                        EDDLandsat8EE.Date_Acquired.desc())[start_rec:(start_rec + n_recs)]
                else:
                    query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Date_Acquired <= start_date,
                                                                      EDDLandsat8EE.Date_Acquired >= end_date,
                                                                      EDDLandsat8EE.Cloud_Cover <= cloud_thres).order_by(
                        EDDLandsat8EE.Date_Acquired.desc()).all()
        else:
            if valid:
                if n_recs > 0:
                    query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Date_Acquired <= start_date,
                                                                      EDDLandsat8EE.Date_Acquired >= end_date,
                                                                      EDDLandsat8EE.Invalid == False,
                                                                      EDDLandsat8EE.ARDProduct == True).order_by(
                        EDDLandsat8EE.Date_Acquired.desc())[start_rec:(start_rec + n_recs)]
                else:
                    query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Date_Acquired <= start_date,
                                                                      EDDLandsat8EE.Date_Acquired >= end_date,
                                                                      EDDLandsat8EE.Invalid == False,
                                                                      EDDLandsat8EE.ARDProduct == True).order_by(
                        EDDLandsat8EE.Date_Acquired.desc()).all()
            else:
                if n_recs > 0:
                    query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Date_Acquired <= start_date,
                                                                      EDDLandsat8EE.Date_Acquired >= end_date).order_by(
                        EDDLandsat8EE.Date_Acquired.desc())[start_rec:(start_rec + n_recs)]
                else:
                    query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Date_Acquired <= start_date,
                                                                      EDDLandsat8EE.Date_Acquired >= end_date).order_by(
                        EDDLandsat8EE.Date_Acquired.desc()).all()
        ses.close()
        scn_records = list()
        if (query_result is not None) and (len(query_result) > 0):
            for rec in query_result:
                scn_records.append(rec)
        else:
            logger.error("No scenes were found within this date range.")
            raise EODataDownException("No scenes were found within this date range.")
        return scn_records

    def query_scn_records_date_bbox_count(self, start_date, end_date, bbox, valid=True, cloud_thres=None):
        """
        A function which queries the database to find scenes within a specified date range
        and returns the number of records available.

        :param start_date: A python datetime object specifying the start date
        :param end_date: A python datetime object specifying the end date
        :param bbox: Bounding box, with which scenes will intersect [West_Lon, East_Lon, South_Lat, North_Lat]
        :param valid: If True only valid scene records will be returned (i.e., has been processed to an ARD product)
        :param cloud_thres: threshold for cloud cover. If None, then ignored.
        :return: count of records available
        """
        west_lon_idx = 0
        east_lon_idx = 1
        south_lat_idx = 2
        north_lat_idx = 3

        logger.debug("Creating Database Engine and Session.")
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()
        logger.debug("Perform query to find scene.")
        if cloud_thres is not None:
            if valid:
                n_rows = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Date_Acquired <= start_date,
                                                            EDDLandsat8EE.Date_Acquired >= end_date,
                                                            EDDLandsat8EE.Invalid == False,
                                                            EDDLandsat8EE.ARDProduct == True,
                                                            EDDLandsat8EE.Cloud_Cover <= cloud_thres).filter(
                                                            (bbox[east_lon_idx] > EDDLandsat8EE.West_Lon),
                                                            (EDDLandsat8EE.East_Lon > bbox[west_lon_idx]),
                                                            (bbox[north_lat_idx] > EDDLandsat8EE.South_Lat),
                                                            (EDDLandsat8EE.North_Lat > bbox[south_lat_idx])).count()
            else:
                n_rows = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Date_Acquired <= start_date,
                                                            EDDLandsat8EE.Date_Acquired >= end_date,
                                                            EDDLandsat8EE.Cloud_Cover <= cloud_thres).filter(
                                                            (bbox[east_lon_idx] > EDDLandsat8EE.West_Lon),
                                                            (EDDLandsat8EE.East_Lon > bbox[west_lon_idx]),
                                                            (bbox[north_lat_idx] > EDDLandsat8EE.South_Lat),
                                                            (EDDLandsat8EE.North_Lat > bbox[south_lat_idx])).count()
        else:
            if valid:
                n_rows = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Date_Acquired <= start_date,
                                                            EDDLandsat8EE.Date_Acquired >= end_date,
                                                            EDDLandsat8EE.Invalid == False,
                                                            EDDLandsat8EE.ARDProduct == True).filter(
                                                            (bbox[east_lon_idx] > EDDLandsat8EE.West_Lon),
                                                            (EDDLandsat8EE.East_Lon > bbox[west_lon_idx]),
                                                            (bbox[north_lat_idx] > EDDLandsat8EE.South_Lat),
                                                            (EDDLandsat8EE.North_Lat > bbox[south_lat_idx])).count()
            else:
                n_rows = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Date_Acquired <= start_date,
                                                            EDDLandsat8EE.Date_Acquired >= end_date).filter(
                                                            (bbox[east_lon_idx] > EDDLandsat8EE.West_Lon),
                                                            (EDDLandsat8EE.East_Lon > bbox[west_lon_idx]),
                                                            (bbox[north_lat_idx] > EDDLandsat8EE.South_Lat),
                                                            (EDDLandsat8EE.North_Lat > bbox[south_lat_idx])).count()
        ses.close()
        return n_rows

    def query_scn_records_date_bbox(self, start_date, end_date, bbox, start_rec=0, n_recs=0, valid=True, cloud_thres=None):
        """
        A function which queries the database to find scenes within a specified date range.
        The order of the records is descending (i.e., from current to historical)

        :param start_date: A python datetime object specifying the start date
        :param end_date: A python datetime object specifying the end date
        :param bbox: Bounding box, with which scenes will intersect [West_Lon, East_Lon, South_Lat, North_Lat]
        :param start_rec: A parameter specifying the start record, for example for pagination.
        :param n_recs: A parameter specifying the number of records to be returned.
        :param valid: If True only valid scene records will be returned (i.e., has been processed to an ARD product)
        :param cloud_thres: threshold for cloud cover. If None, then ignored.
        :return: list of database records
        """
        west_lon_idx = 0
        east_lon_idx = 1
        south_lat_idx = 2
        north_lat_idx = 3

        logger.debug("Creating Database Engine and Session.")
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()
        logger.debug("Perform query to find scene.")
        if cloud_thres is not None:
            if valid:
                if n_recs > 0:
                    query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Date_Acquired <= start_date,
                                                                      EDDLandsat8EE.Date_Acquired >= end_date,
                                                                      EDDLandsat8EE.Invalid == False,
                                                                      EDDLandsat8EE.ARDProduct == True,
                                                                      EDDLandsat8EE.Cloud_Cover <= cloud_thres).filter(
                                                                      (bbox[east_lon_idx] > EDDLandsat8EE.West_Lon),
                                                                      (EDDLandsat8EE.East_Lon > bbox[west_lon_idx]),
                                                                      (bbox[north_lat_idx] > EDDLandsat8EE.South_Lat),
                                                                      (EDDLandsat8EE.North_Lat > bbox[south_lat_idx])).order_by(
                        EDDLandsat8EE.Date_Acquired.desc())[start_rec:(start_rec + n_recs)]
                else:
                    query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Date_Acquired <= start_date,
                                                                      EDDLandsat8EE.Date_Acquired >= end_date,
                                                                      EDDLandsat8EE.Invalid == False,
                                                                      EDDLandsat8EE.ARDProduct == True,
                                                                      EDDLandsat8EE.Cloud_Cover <= cloud_thres).filter(
                                                                      (bbox[east_lon_idx] > EDDLandsat8EE.West_Lon),
                                                                      (EDDLandsat8EE.East_Lon > bbox[west_lon_idx]),
                                                                      (bbox[north_lat_idx] > EDDLandsat8EE.South_Lat),
                                                                      (EDDLandsat8EE.North_Lat > bbox[south_lat_idx])).order_by(
                        EDDLandsat8EE.Date_Acquired.desc()).all()
            else:
                if n_recs > 0:
                    query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Date_Acquired <= start_date,
                                                                      EDDLandsat8EE.Date_Acquired >= end_date,
                                                                      EDDLandsat8EE.Cloud_Cover <= cloud_thres).filter(
                                                                      (bbox[east_lon_idx] > EDDLandsat8EE.West_Lon),
                                                                      (EDDLandsat8EE.East_Lon > bbox[west_lon_idx]),
                                                                      (bbox[north_lat_idx] > EDDLandsat8EE.South_Lat),
                                                                      (EDDLandsat8EE.North_Lat > bbox[south_lat_idx])).order_by(
                        EDDLandsat8EE.Date_Acquired.desc())[start_rec:(start_rec + n_recs)]
                else:
                    query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Date_Acquired <= start_date,
                                                                      EDDLandsat8EE.Date_Acquired >= end_date,
                                                                      EDDLandsat8EE.Cloud_Cover <= cloud_thres).filter(
                                                                      (bbox[east_lon_idx] > EDDLandsat8EE.West_Lon),
                                                                      (EDDLandsat8EE.East_Lon > bbox[west_lon_idx]),
                                                                      (bbox[north_lat_idx] > EDDLandsat8EE.South_Lat),
                                                                      (EDDLandsat8EE.North_Lat > bbox[south_lat_idx])).order_by(
                        EDDLandsat8EE.Date_Acquired.desc()).all()
        else:
            if valid:
                if n_recs > 0:
                    query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Date_Acquired <= start_date,
                                                                      EDDLandsat8EE.Date_Acquired >= end_date,
                                                                      EDDLandsat8EE.Invalid == False,
                                                                      EDDLandsat8EE.ARDProduct == True).filter(
                                                                      (bbox[east_lon_idx] > EDDLandsat8EE.West_Lon),
                                                                      (EDDLandsat8EE.East_Lon > bbox[west_lon_idx]),
                                                                      (bbox[north_lat_idx] > EDDLandsat8EE.South_Lat),
                                                                      (EDDLandsat8EE.North_Lat > bbox[south_lat_idx])).order_by(
                        EDDLandsat8EE.Date_Acquired.desc())[start_rec:(start_rec + n_recs)]
                else:
                    query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Date_Acquired <= start_date,
                                                                      EDDLandsat8EE.Date_Acquired >= end_date,
                                                                      EDDLandsat8EE.Invalid == False,
                                                                      EDDLandsat8EE.ARDProduct == True).filter(
                                                                      (bbox[east_lon_idx] > EDDLandsat8EE.West_Lon),
                                                                      (EDDLandsat8EE.East_Lon > bbox[west_lon_idx]),
                                                                      (bbox[north_lat_idx] > EDDLandsat8EE.South_Lat),
                                                                      (EDDLandsat8EE.North_Lat > bbox[south_lat_idx])).order_by(
                        EDDLandsat8EE.Date_Acquired.desc()).all()
            else:
                if n_recs > 0:
                    query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Date_Acquired <= start_date,
                                                                      EDDLandsat8EE.Date_Acquired >= end_date).filter(
                                                                      (bbox[east_lon_idx] > EDDLandsat8EE.West_Lon),
                                                                      (EDDLandsat8EE.East_Lon > bbox[west_lon_idx]),
                                                                      (bbox[north_lat_idx] > EDDLandsat8EE.South_Lat),
                                                                      (EDDLandsat8EE.North_Lat > bbox[south_lat_idx])).order_by(
                        EDDLandsat8EE.Date_Acquired.desc())[start_rec:(start_rec + n_recs)]
                else:
                    query_result = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Date_Acquired <= start_date,
                                                                      EDDLandsat8EE.Date_Acquired >= end_date).filter(
                                                                      (bbox[east_lon_idx] > EDDLandsat8EE.West_Lon),
                                                                      (EDDLandsat8EE.East_Lon > bbox[west_lon_idx]),
                                                                      (bbox[north_lat_idx] > EDDLandsat8EE.South_Lat),
                                                                      (EDDLandsat8EE.North_Lat > bbox[south_lat_idx])).order_by(
                        EDDLandsat8EE.Date_Acquired.desc()).all()
        ses.close()
        scn_records = list()
        if (query_result is not None) and (len(query_result) > 0):
            for rec in query_result:
                scn_records.append(rec)
        else:
            logger.error("No scenes were found within this date range.")
            raise EODataDownException("No scenes were found within this date range.")
        return scn_records

    def find_unique_scn_dates(self, start_date, end_date, valid=True, order_desc=True, platform=None):
        """
        A function which returns a list of unique dates on which acquisitions have occurred.
        :param start_date: A python datetime object specifying the start date (most recent date)
        :param end_date: A python datetime object specifying the end date (earliest date)
        :param valid: If True only valid observations are considered.
        :return: List of datetime.date objects.
        """
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()

        if platform is None:
            if valid:
                if order_desc:
                    scn_dates = ses.query(sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date)).filter(
                        EDDLandsat8EE.Date_Acquired <= start_date,
                        EDDLandsat8EE.Date_Acquired >= end_date,
                        EDDLandsat8EE.Invalid == False).group_by(
                        sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date)).order_by(
                        sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date).desc())
                else:
                    scn_dates = ses.query(sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date)).filter(
                            EDDLandsat8EE.Date_Acquired <= start_date,
                            EDDLandsat8EE.Date_Acquired >= end_date,
                            EDDLandsat8EE.Invalid == False).group_by(
                            sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date)).order_by(
                            sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date).asc())
            else:
                if order_desc:
                    scn_dates = ses.query(sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date)).filter(
                        EDDLandsat8EE.Date_Acquired <= start_date,
                        EDDLandsat8EE.Date_Acquired >= end_date).group_by(
                        sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date)).order_by(
                        sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date).desc())
                else:
                    scn_dates = ses.query(sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date)).filter(
                            EDDLandsat8EE.Date_Acquired <= start_date,
                            EDDLandsat8EE.Date_Acquired >= end_date).group_by(
                            sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date)).order_by(
                            sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date).asc())
        else:
            if valid:
                if order_desc:
                    scn_dates = ses.query(sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date)).filter(
                        EDDLandsat8EE.Date_Acquired <= start_date,
                        EDDLandsat8EE.Date_Acquired >= end_date,
                        EDDLandsat8EE.Invalid == False,
                        EDDLandsat8EE.Spacecraft_ID == platform).group_by(
                        sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date)).order_by(
                        sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date).desc())
                else:
                    scn_dates = ses.query(sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date)).filter(
                            EDDLandsat8EE.Date_Acquired <= start_date,
                            EDDLandsat8EE.Date_Acquired >= end_date,
                            EDDLandsat8EE.Invalid == False,
                            EDDLandsat8EE.Spacecraft_ID == platform).group_by(
                            sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date)).order_by(
                            sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date).asc())
            else:
                if order_desc:
                    scn_dates = ses.query(sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date)).filter(
                        EDDLandsat8EE.Date_Acquired <= start_date,
                        EDDLandsat8EE.Date_Acquired >= end_date,
                        EDDLandsat8EE.Spacecraft_ID == platform).group_by(
                        sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date)).order_by(
                        sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date).desc())
                else:
                    scn_dates = ses.query(sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date)).filter(
                            EDDLandsat8EE.Date_Acquired <= start_date,
                            EDDLandsat8EE.Date_Acquired >= end_date,
                            EDDLandsat8EE.Spacecraft_ID == platform).group_by(
                            sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date)).order_by(
                            sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date).asc())
        ses.close()
        return scn_dates

    def get_scns_for_date(self, date_of_interest, valid=True, ard_prod=True, platform=None):
        """
        A function to retrieve a list of scenes which have been acquired on a particular date.

        :param date_of_interest: a datetime.date object specifying the date of interest.
        :param valid: If True only valid observations are considered.
        :param ard_prod: If True only observations which have been converted to an ARD product are considered.
        :param platform: If None then all scenes, if value provided then it just be for that platform.
        :return: a list of sensor objects
        """
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()

        if platform is None:
            if valid and ard_prod:
                scns = ses.query(EDDLandsat8EE).filter(
                        sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date) == date_of_interest,
                        EDDLandsat8EE.Invalid == False, EDDLandsat8EE.ARDProduct == True).all()
            elif valid:
                scns = ses.query(EDDLandsat8EE).filter(
                        sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date) == date_of_interest,
                        EDDLandsat8EE.Invalid == False).all()
            elif ard_prod:
                scns = ses.query(EDDLandsat8EE).filter(
                        sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date) == date_of_interest,
                        EDDLandsat8EE.ARDProduct == True).all()
            else:
                scns = ses.query(EDDLandsat8EE).filter(
                        sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date) == date_of_interest).all()
        else:
            if valid and ard_prod:
                scns = ses.query(EDDLandsat8EE).filter(
                        sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date) == date_of_interest,
                        EDDLandsat8EE.Invalid == False, EDDLandsat8EE.ARDProduct == True,
                        EDDLandsat8EE.Spacecraft_ID == platform).all()
            elif valid:
                scns = ses.query(EDDLandsat8EE).filter(
                        sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date) == date_of_interest,
                        EDDLandsat8EE.Invalid == False, EDDLandsat8EE.Spacecraft_ID == platform).all()
            elif ard_prod:
                scns = ses.query(EDDLandsat8EE).filter(
                        sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date) == date_of_interest,
                        EDDLandsat8EE.ARDProduct == True, EDDLandsat8EE.Spacecraft_ID == platform).all()
            else:
                scns = ses.query(EDDLandsat8EE).filter(
                        sqlalchemy.cast(EDDLandsat8EE.Date_Acquired, sqlalchemy.Date) == date_of_interest,
                        EDDLandsat8EE.Spacecraft_ID == platform).all()
        return scns

    def get_scn_pids_for_date(self, date_of_interest, valid=True, ard_prod=True, platform=None):
        """
        A function to retrieve a list of scene PIDs which have been acquired on a particular date.

        :param date_of_interest: a datetime.date object specifying the date of interest.
        :param valid: If True only valid observations are considered.
        :param ard_prod: If True only observations which have been converted to an ARD product are considered.
        :param platform: If None then all scenes, if value provided then it just be for that platform.
        :return: a list of PIDs (ints)
        """
        scns = self.get_scns_for_date(date_of_interest, valid, ard_prod, platform)
        scn_pids = list()
        for scn in scns:
            scn_pids.append(scn.PID)
        return scn_pids

    def create_scn_date_imgs(self, start_date, end_date, img_size, out_img_dir, img_format, vec_file, vec_lyr,
                             tmp_dir, order_desc=True):
        """
        A function which created stretched and formatted visualisation images by combining all the scenes
        for a particular date. It does that for each of the unique dates within the date range specified.

        :param start_date: A python datetime object specifying the start date (most recent date)
        :param end_date: A python datetime object specifying the end date (earliest date)
        :param img_size: The output image size in pixels
        :param out_img_dir: The output image directory
        :param img_format: the output image format (JPEG, PNG or GTIFF)
        :param vec_file: A vector file (polyline) which can be overlaid for context.
        :param vec_lyr: The layer in the vector file.
        :param tmp_dir: A temp directory for intermediate files.
        :return: dict with date (YYYYMMDD) as key with a dict of image info, including
                 an qkimage field for the generated image
        """
        out_img_ext = 'png'
        if img_format.upper() == 'PNG':
            out_img_ext = 'png'
        elif img_format.upper() == 'JPEG':
            out_img_ext = 'jpg'
        elif img_format.upper() == 'GTIFF':
            out_img_ext = 'tif'
        else:
            raise EODataDownException("The input image format ({}) was recognised".format(img_format))
        eoddutils = eodatadown.eodatadownutils.EODataDownUtils()
        scn_dates = self.find_unique_scn_dates(start_date, end_date, valid=True, order_desc=order_desc)
        scn_qklks = dict()
        for scn_date in scn_dates:
            print("Processing {}:".format(scn_date[0].strftime('%Y-%m-%d')))
            scns = self.get_scns_for_date(scn_date[0])
            scn_files = []
            first = True
            spacecraft = ''
            for scn in scns:
                ard_file = eoddutils.findFile(scn.ARDProduct_Path, "*vmsk_rad_srefdem_stdsref.tif")

                print("\t{}: {} {} - {}".format(scn.PID, scn.Spacecraft_ID, scn.Scene_ID, ard_file))
                scn_files.append(ard_file)
                if first:
                    spacecraft = scn.Spacecraft_ID
                    first = False
                elif spacecraft.upper() != scn.Spacecraft_ID.upper():
                    raise Exception("The input images are from different sensors which cannot be mixed.")

            bands = '4,5,3'
            if spacecraft.upper() == 'LANDSAT_8'.upper():
                bands = '5,6,4'

            scn_date_str = scn_date[0].strftime('%Y%m%d')
            quicklook_img = os.path.join(out_img_dir, "ls_qklk_{}.{}".format(scn_date_str, out_img_ext))
            import rsgislib.tools.visualisation
            rsgislib.tools.visualisation.createQuicklookOverviewImgsVecOverlay(scn_files, bands, tmp_dir,
                                                                               vec_file, vec_lyr,
                                                                               outputImgs=quicklook_img,
                                                                               output_img_sizes=img_size,
                                                                               gdalformat=img_format,
                                                                               scale_axis='auto',
                                                                               stretch_file=self.std_vis_img_stch,
                                                                               overlay_clr=[255, 255, 255])
            scn_qklks[scn_date_str] = dict()
            scn_qklks[scn_date_str]['qkimage'] = quicklook_img
            scn_qklks[scn_date_str]['scn_date'] = scn_date[0]
        return scn_qklks

    def create_multi_scn_visual(self, scn_pids, out_imgs, out_img_sizes, out_extent_vec, out_extent_lyr,
                                gdal_format, tmp_dir):
        """

        :param scn_pids: A list of scene PIDs (scenes without an ARD image are ignored silently)
        :param out_imgs: A list of output image files
        :param out_img_sizes: A list of output image sizes.
        :param out_extent_vec: A vector file defining the output image extent (can be None)
        :param out_extent_lyr: A vector layer name for the layer defining the output image extent (can be None)
        :param gdal_format: The GDAL file format of the output images (e.g., GTIFF)
        :param tmp_dir: A directory for temporary files to be written to.
        :return: boolean. True: Completed. False: Failed to complete - invalid.
        """
        eoddutils = eodatadown.eodatadownutils.EODataDownUtils()
        # Get the ARD images.
        ard_images = []
        first = True
        spacecraft = ''
        for pid in scn_pids:
            scn = self.get_scn_record(pid)
            # Look for data which has been processed with ARCSI
            try:
                ard_file = eodd_utils.findFile(scn.ARDProduct_Path, '*vmsk_rad_srefdem_stdsref.tif')
            except:
                # Then check for L2 data downloaded from USGS with a VRT stack of all bands
                ard_file = eodd_utils.findFile(scn.ARDProduct_Path, '*_stack.vrt')

            if ard_file is not None:
                ard_images.append(ard_file)
            if first:
                spacecraft = scn.Spacecraft_ID
                first = False
            elif spacecraft.upper() != scn.Spacecraft_ID.upper():
                raise Exception("The input images are from different sensors which cannot be mixed.")

        if len(ard_images) > 0:
            bands = '4,5,3'
            if spacecraft.upper() == 'LANDSAT_8'.upper():
                bands = '5,6,4'

            export_stretch_file = False
            strch_file = self.std_vis_img_stch
            if self.std_vis_img_stch is None:
                export_stretch_file = True
                strch_file_basename = eoddutils.get_file_basename(out_imgs[0], n_comps=3)
                strch_file_path = os.path.split(out_imgs[0])[0]
                strch_file = os.path.join(strch_file_path, "{}_srtch_stats.txt".format(strch_file_basename))

            import rsgislib.tools.visualisation
            rsgislib.tools.visualisation.createVisualOverviewImgsVecExtent(ard_images, bands, tmp_dir,
                                                                           out_extent_vec, out_extent_lyr,
                                                                           out_imgs, out_img_sizes, gdal_format,
                                                                           'auto', strch_file, export_stretch_file)
            return True
        # else there weren't any ard_images...
        return False

    def query_scn_records_bbox(self, lat_north, lat_south, lon_east, lon_west):
        """
        A function which queries the database to find scenes within a specified bounding box.
        :param lat_north: double with latitude north
        :param lat_south: double with latitude south
        :param lon_east: double with longitude east
        :param lon_west: double with longitude west
        :return: list of database records.
        """
        raise EODataDownException("Not implemented.")

    def update_dwnld_path(self, replace_path, new_path):
        """
        If the path to the downloaded files is updated then this function will update the database
        replacing the part of the path which has been changed. The files will also be moved (if they have
        not already been moved) during the processing. If they are no present at the existing location
        in the database or at the new path then this process will not complete.
        :param replace_path: The existing path to be replaced.
        :param new_path: The new path where the downloaded files will be located.
        """
        raise EODataDownException("Not implemented.")

    def update_ard_path(self, replace_path, new_path):
        """
        If the path to the ARD files is updated then this function will update the database
        replacing the part of the path which has been changed. The files will also be moved (if they have
        not already been moved) during the processing. If they are no present at the existing location
        in the database or at the new path then this process will not complete.
        :param replace_path: The existing path to be replaced.
        :param new_path: The new path where the downloaded files will be located.
        """
        raise EODataDownException("Not implemented.")

    def dwnlds_archived(self, replace_path=None, new_path=None):
        """
        This function identifies scenes which have been downloaded but the download is no longer available
        in the download path. It will set the archived option on the database for these files. It is expected
        that these files will have been move to an archive location (e.g., AWS glacier or tape etc.) but they
        could have just be deleted. There is an option to update the path to the downloads if inputs are not
        None but a check will not be performed as to whether the data is present at the new path.
        :param replace_path: The existing path to be replaced.
        :param new_path: The new path where the downloaded files are located.
        """
        raise EODataDownException("Not implemented.")

    def export_db_to_json(self, out_json_file):
        """
        This function exports the database table to a JSON file.
        :param out_json_file: output JSON file path.
        """
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()

        eodd_utils = eodatadown.eodatadownutils.EODataDownUtils()

        query_result = ses.query(EDDLandsat8EE).all()
        db_scn_dict = dict()
        for scn in query_result:
            db_scn_dict[scn.PID] = dict()
            db_scn_dict[scn.PID]['PID'] = scn.PID
            db_scn_dict[scn.PID]['Scene_ID'] = scn.Scene_ID
            db_scn_dict[scn.PID]['Product_ID'] = scn.Product_ID
            db_scn_dict[scn.PID]['Spacecraft_ID'] = scn.Spacecraft_ID
            db_scn_dict[scn.PID]['Sensor_ID'] = scn.Sensor_ID
            db_scn_dict[scn.PID]['Date_Acquired'] = eodd_utils.getDateTimeAsString(scn.Date_Acquired)
            db_scn_dict[scn.PID]['Collection_Number'] = scn.Collection_Number
            db_scn_dict[scn.PID]['Collection_Category'] = scn.Collection_Category
            db_scn_dict[scn.PID]['Sensing_Time'] = eodd_utils.getDateTimeAsString(scn.Sensing_Time)
            db_scn_dict[scn.PID]['Data_Type'] = scn.Data_Type
            db_scn_dict[scn.PID]['WRS_Path'] = scn.WRS_Path
            db_scn_dict[scn.PID]['WRS_Row'] = scn.WRS_Row
            db_scn_dict[scn.PID]['Cloud_Cover'] = scn.Cloud_Cover
            db_scn_dict[scn.PID]['North_Lat'] = scn.North_Lat
            db_scn_dict[scn.PID]['South_Lat'] = scn.South_Lat
            db_scn_dict[scn.PID]['East_Lon'] = scn.East_Lon
            db_scn_dict[scn.PID]['West_Lon'] = scn.West_Lon
            db_scn_dict[scn.PID]['Total_Size'] = scn.Total_Size
            db_scn_dict[scn.PID]['Remote_URL'] = scn.Remote_URL
            db_scn_dict[scn.PID]['Query_Date'] = eodd_utils.getDateTimeAsString(scn.Query_Date)
            db_scn_dict[scn.PID]['Download_Start_Date'] = eodd_utils.getDateTimeAsString(scn.Download_Start_Date)
            db_scn_dict[scn.PID]['Download_End_Date'] = eodd_utils.getDateTimeAsString(scn.Download_End_Date)
            db_scn_dict[scn.PID]['Downloaded'] = scn.Downloaded
            db_scn_dict[scn.PID]['Download_Path'] = scn.Download_Path
            db_scn_dict[scn.PID]['Archived'] = scn.Archived
            db_scn_dict[scn.PID]['ARDProduct_Start_Date'] = eodd_utils.getDateTimeAsString(scn.ARDProduct_Start_Date)
            db_scn_dict[scn.PID]['ARDProduct_End_Date'] = eodd_utils.getDateTimeAsString(scn.ARDProduct_End_Date)
            db_scn_dict[scn.PID]['ARDProduct'] = scn.ARDProduct
            db_scn_dict[scn.PID]['ARDProduct_Path'] = scn.ARDProduct_Path
            db_scn_dict[scn.PID]['DCLoaded_Start_Date'] = eodd_utils.getDateTimeAsString(scn.DCLoaded_Start_Date)
            db_scn_dict[scn.PID]['DCLoaded_End_Date'] = eodd_utils.getDateTimeAsString(scn.DCLoaded_End_Date)
            db_scn_dict[scn.PID]['DCLoaded'] = scn.DCLoaded
            db_scn_dict[scn.PID]['Invalid'] = scn.Invalid
            db_scn_dict[scn.PID]['ExtendedInfo'] = scn.ExtendedInfo
            db_scn_dict[scn.PID]['RegCheck'] = scn.RegCheck

        db_plgin_dict = dict()
        if self.calc_scn_usr_analysis():
            plugin_keys = self.get_usr_analysis_keys()
            for plgin_key in plugin_keys:
                query_result = ses.query(EDDLandsat8EEPlugins).filter(EDDLandsat8EEPlugins.PlugInName == plgin_key).all()
                db_plgin_dict[plgin_key] = dict()
                for scn in query_result:
                    db_plgin_dict[plgin_key][scn.Scene_PID] = dict()
                    db_plgin_dict[plgin_key][scn.Scene_PID]['Scene_PID'] = scn.Scene_PID
                    db_plgin_dict[plgin_key][scn.Scene_PID]['PlugInName'] = scn.PlugInName
                    db_plgin_dict[plgin_key][scn.Scene_PID]['Start_Date'] = eodd_utils.getDateTimeAsString(scn.Start_Date)
                    db_plgin_dict[plgin_key][scn.Scene_PID]['End_Date'] = eodd_utils.getDateTimeAsString(scn.End_Date)
                    db_plgin_dict[plgin_key][scn.Scene_PID]['Completed'] = scn.Completed
                    db_plgin_dict[plgin_key][scn.Scene_PID]['Success'] = scn.Success
                    db_plgin_dict[plgin_key][scn.Scene_PID]['Outputs'] = scn.Outputs
                    db_plgin_dict[plgin_key][scn.Scene_PID]['Error'] = scn.Error
                    db_plgin_dict[plgin_key][scn.Scene_PID]['ExtendedInfo'] = scn.ExtendedInfo
        ses.close()

        fnl_out_dict = dict()
        fnl_out_dict['scn_db'] = db_scn_dict
        if db_plgin_dict:
            fnl_out_dict['plgin_db'] = db_plgin_dict

        with open(out_json_file, 'w') as outfile:
            json.dump(fnl_out_dict, outfile, indent=4, separators=(',', ': '), ensure_ascii=False)

    def import_sensor_db(self, input_json_file, replace_path_dict=None):
        """
        This function imports from the database records from the specified input JSON file.

        :param input_json_file: input JSON file with the records to be imported.
        :param replace_path_dict: a dictionary of file paths to be updated, if None then ignored.
        """
        db_records = list()
        db_plgin_records = list()
        eodd_utils = eodatadown.eodatadownutils.EODataDownUtils()
        with open(input_json_file) as json_file_obj:
            db_data = json.load(json_file_obj)
            if 'scn_db' in db_data:
                sensor_rows = db_data['scn_db']
            else:
                sensor_rows = db_data
            for pid in sensor_rows:
                # This is due to typo - in original table def so will keep this for a while to allow export and import
                if 'Collection_Category' in sensor_rows[pid]:
                    collect_cat = sensor_rows[pid]['Collection_Category']
                else:
                    collect_cat = sensor_rows[pid]['Collection_Catagory']
                db_records.append(EDDLandsat8EE(PID=sensor_rows[pid]['PID'],
                                                   Scene_ID=sensor_rows[pid]['Scene_ID'],
                                                   Product_ID=sensor_rows[pid]['Product_ID'],
                                                   Spacecraft_ID=sensor_rows[pid]['Spacecraft_ID'],
                                                   Sensor_ID=sensor_rows[pid]['Sensor_ID'],
                                                   Date_Acquired=eodd_utils.getDateTimeFromISOString(sensor_rows[pid]['Date_Acquired']),
                                                   Collection_Number=sensor_rows[pid]['Collection_Number'],
                                                   Collection_Category=collect_cat,
                                                   Sensing_Time=eodd_utils.getDateTimeFromISOString(sensor_rows[pid]['Sensing_Time']),
                                                   Data_Type=sensor_rows[pid]['Data_Type'],
                                                   WRS_Path=sensor_rows[pid]['WRS_Path'],
                                                   WRS_Row=sensor_rows[pid]['WRS_Row'],
                                                   Cloud_Cover=sensor_rows[pid]['Cloud_Cover'],
                                                   North_Lat=sensor_rows[pid]['North_Lat'],
                                                   South_Lat=sensor_rows[pid]['South_Lat'],
                                                   East_Lon=sensor_rows[pid]['East_Lon'],
                                                   West_Lon=sensor_rows[pid]['West_Lon'],
                                                   Total_Size=sensor_rows[pid]['Total_Size'],
                                                   Remote_URL=sensor_rows[pid]['Remote_URL'],
                                                   Query_Date=eodd_utils.getDateTimeFromISOString(sensor_rows[pid]['Query_Date']),
                                                   Download_Start_Date=eodd_utils.getDateTimeFromISOString(sensor_rows[pid]['Download_Start_Date']),
                                                   Download_End_Date=eodd_utils.getDateTimeFromISOString(sensor_rows[pid]['Download_End_Date']),
                                                   Downloaded=sensor_rows[pid]['Downloaded'],
                                                   Download_Path=eodd_utils.update_file_path(sensor_rows[pid]['Download_Path'], replace_path_dict),
                                                   Archived=sensor_rows[pid]['Archived'],
                                                   ARDProduct_Start_Date=eodd_utils.getDateTimeFromISOString(sensor_rows[pid]['ARDProduct_Start_Date']),
                                                   ARDProduct_End_Date=eodd_utils.getDateTimeFromISOString(sensor_rows[pid]['ARDProduct_End_Date']),
                                                   ARDProduct=sensor_rows[pid]['ARDProduct'],
                                                   ARDProduct_Path=eodd_utils.update_file_path(sensor_rows[pid]['ARDProduct_Path'], replace_path_dict),
                                                   DCLoaded_Start_Date=eodd_utils.getDateTimeFromISOString(sensor_rows[pid]['DCLoaded_Start_Date']),
                                                   DCLoaded_End_Date=eodd_utils.getDateTimeFromISOString(sensor_rows[pid]['DCLoaded_End_Date']),
                                                   DCLoaded=sensor_rows[pid]['DCLoaded'],
                                                   Invalid=sensor_rows[pid]['Invalid'],
                                                   ExtendedInfo=self.update_extended_info_qklook_tilecache_paths(sensor_rows[pid]['ExtendedInfo'], replace_path_dict),
                                                   RegCheck=sensor_rows[pid]['RegCheck']))

            if 'plgin_db' in db_data:
                plgin_rows = db_data['plgin_db']
                for plgin_key in plgin_rows:
                    for scn_pid in plgin_rows[plgin_key]:
                        db_plgin_records.append(EDDLandsat8EEPlugins(Scene_PID=plgin_rows[plgin_key][scn_pid]['Scene_PID'],
                                                                        PlugInName=plgin_rows[plgin_key][scn_pid]['PlugInName'],
                                                                        Start_Date=eodd_utils.getDateTimeFromISOString(plgin_rows[plgin_key][scn_pid]['Start_Date']),
                                                                        End_Date=eodd_utils.getDateTimeFromISOString(plgin_rows[plgin_key][scn_pid]['End_Date']),
                                                                        Completed=plgin_rows[plgin_key][scn_pid]['Completed'],
                                                                        Success=plgin_rows[plgin_key][scn_pid]['Success'],
                                                                        Outputs=plgin_rows[plgin_key][scn_pid]['Outputs'],
                                                                        Error=plgin_rows[plgin_key][scn_pid]['Error'],
                                                                        ExtendedInfo=plgin_rows[plgin_key][scn_pid]['ExtendedInfo']))

        if len(db_records) > 0:
            db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
            session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
            ses = session_sqlalc()
            ses.add_all(db_records)
            ses.commit()
            if len(db_plgin_records) > 0:
                ses.add_all(db_plgin_records)
                ses.commit()
            ses.close()

    def create_gdal_gis_lyr(self, file_path, lyr_name, driver_name='GPKG', add_lyr=False):
        """
        A function to export the outlines and some attributes to a GDAL vector layer.
        :param file_path: path to the output file.
        :param lyr_name: the name of the layer within the output file.
        :param driver_name: name of the gdal driver
        :param add_lyr: add the layer to the file
        """
        try:
            gdal.UseExceptions()

            vec_osr = osr.SpatialReference()
            vec_osr.ImportFromEPSG(4326)

            driver = ogr.GetDriverByName(driver_name)
            if os.path.exists(file_path) and add_lyr:
                out_data_source = gdal.OpenEx(file_path, gdal.OF_UPDATE)
            elif os.path.exists(file_path):
                driver.DeleteDataSource(file_path)
                out_data_source = driver.CreateDataSource(file_path)
            else:
                out_data_source = driver.CreateDataSource(file_path)

            out_vec_lyr = out_data_source.GetLayerByName(lyr_name)
            if out_vec_lyr is None:
                out_vec_lyr = out_data_source.CreateLayer(lyr_name, srs=vec_osr, geom_type=ogr.wkbPolygon)

            pid_field_defn = ogr.FieldDefn("PID", ogr.OFTInteger)
            if out_vec_lyr.CreateField(pid_field_defn) != 0:
                raise EODataDownException("Could not create 'PID' field in output vector lyr.")

            scene_id_field_defn = ogr.FieldDefn("Scene_ID", ogr.OFTString)
            scene_id_field_defn.SetWidth(256)
            if out_vec_lyr.CreateField(scene_id_field_defn) != 0:
                raise EODataDownException("Could not create 'Scene_ID' field in output vector lyr.")

            product_id_field_defn = ogr.FieldDefn("Product_ID", ogr.OFTString)
            product_id_field_defn.SetWidth(256)
            if out_vec_lyr.CreateField(product_id_field_defn) != 0:
                raise EODataDownException("Could not create 'Product_ID' field in output vector lyr.")

            spacecraft_id_field_defn = ogr.FieldDefn("Spacecraft_ID", ogr.OFTString)
            spacecraft_id_field_defn.SetWidth(256)
            if out_vec_lyr.CreateField(spacecraft_id_field_defn) != 0:
                raise EODataDownException("Could not create 'Spacecraft_ID' field in output vector lyr.")

            sensor_id_field_defn = ogr.FieldDefn("Sensor_ID", ogr.OFTString)
            sensor_id_field_defn.SetWidth(256)
            if out_vec_lyr.CreateField(sensor_id_field_defn) != 0:
                raise EODataDownException("Could not create 'Sensor_ID' field in output vector lyr.")

            date_acq_field_defn = ogr.FieldDefn("Date_Acquired", ogr.OFTString)
            date_acq_field_defn.SetWidth(32)
            if out_vec_lyr.CreateField(date_acq_field_defn) != 0:
                raise EODataDownException("Could not create 'Date_Acquired' field in output vector lyr.")

            collect_num_field_defn = ogr.FieldDefn("Collection_Number", ogr.OFTString)
            collect_num_field_defn.SetWidth(256)
            if out_vec_lyr.CreateField(collect_num_field_defn) != 0:
                raise EODataDownException("Could not create 'Collection_Number' field in output vector lyr.")

            collect_cat_field_defn = ogr.FieldDefn("Collection_Category", ogr.OFTString)
            collect_cat_field_defn.SetWidth(256)
            if out_vec_lyr.CreateField(collect_cat_field_defn) != 0:
                raise EODataDownException("Could not create 'Collection_Category' field in output vector lyr.")

            sense_time_field_defn = ogr.FieldDefn("Sensing_Time", ogr.OFTString)
            sense_time_field_defn.SetWidth(32)
            if out_vec_lyr.CreateField(sense_time_field_defn) != 0:
                raise EODataDownException("Could not create 'Sensing_Time' field in output vector lyr.")

            wrs_path_field_defn = ogr.FieldDefn("WRS_Path", ogr.OFTInteger)
            if out_vec_lyr.CreateField(wrs_path_field_defn) != 0:
                raise EODataDownException("Could not create 'WRS_Path' field in output vector lyr.")

            wrs_row_field_defn = ogr.FieldDefn("WRS_Row", ogr.OFTInteger)
            if out_vec_lyr.CreateField(wrs_row_field_defn) != 0:
                raise EODataDownException("Could not create 'WRS_Row' field in output vector lyr.")

            cloud_cover_field_defn = ogr.FieldDefn("Cloud_Cover", ogr.OFTReal)
            if out_vec_lyr.CreateField(cloud_cover_field_defn) != 0:
                raise EODataDownException("Could not create 'Cloud_Cover' field in output vector lyr.")

            down_path_field_defn = ogr.FieldDefn("Download_Path", ogr.OFTString)
            down_path_field_defn.SetWidth(256)
            if out_vec_lyr.CreateField(down_path_field_defn) != 0:
                raise EODataDownException("Could not create 'Download_Path' field in output vector lyr.")

            ard_path_field_defn = ogr.FieldDefn("ARD_Path", ogr.OFTString)
            ard_path_field_defn.SetWidth(256)
            if out_vec_lyr.CreateField(ard_path_field_defn) != 0:
                raise EODataDownException("Could not create 'ARD_Path' field in output vector lyr.")

            north_field_defn = ogr.FieldDefn("North_Lat", ogr.OFTReal)
            if out_vec_lyr.CreateField(north_field_defn) != 0:
                raise EODataDownException("Could not create 'North_Lat' field in output vector lyr.")

            south_field_defn = ogr.FieldDefn("South_Lat", ogr.OFTReal)
            if out_vec_lyr.CreateField(south_field_defn) != 0:
                raise EODataDownException("Could not create 'South_Lat' field in output vector lyr.")

            east_field_defn = ogr.FieldDefn("East_Lon", ogr.OFTReal)
            if out_vec_lyr.CreateField(east_field_defn) != 0:
                raise EODataDownException("Could not create 'East_Lon' field in output vector lyr.")

            west_field_defn = ogr.FieldDefn("West_Lon", ogr.OFTReal)
            if out_vec_lyr.CreateField(west_field_defn) != 0:
                raise EODataDownException("Could not create 'West_Lon' field in output vector lyr.")

            # Get the output Layer's Feature Definition
            feature_defn = out_vec_lyr.GetLayerDefn()

            logger.debug("Creating Database Engine and Session.")
            db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
            db_session = sqlalchemy.orm.sessionmaker(bind=db_engine)
            db_ses = db_session()

            query_rtn = db_ses.query(EDDLandsat8EE).all()

            if len(query_rtn) > 0:
                for record in query_rtn:
                    geo_bbox = eodatadown.eodatadownutils.EDDGeoBBox()
                    geo_bbox.setBBOX(record.North_Lat, record.South_Lat, record.West_Lon, record.East_Lon)
                    bboxs = geo_bbox.getGeoBBoxsCut4LatLonBounds()

                    for bbox in bboxs:
                        poly = bbox.getOGRPolygon()
                        # Add to output shapefile.
                        out_feat = ogr.Feature(feature_defn)
                        out_feat.SetField("PID", record.PID)
                        out_feat.SetField("Scene_ID", record.Scene_ID)
                        out_feat.SetField("Product_ID", record.Product_ID)
                        out_feat.SetField("Spacecraft_ID", record.Spacecraft_ID)
                        out_feat.SetField("Sensor_ID", record.Sensor_ID)
                        out_feat.SetField("Date_Acquired", record.Date_Acquired.strftime('%Y-%m-%d'))
                        out_feat.SetField("Collection_Number", record.Collection_Number)
                        out_feat.SetField("Collection_Category", record.Collection_Category)
                        out_feat.SetField("Sensing_Time", record.Sensing_Time.strftime('%Y-%m-%d %H:%M:%S'))
                        out_feat.SetField("WRS_Path", record.WRS_Path)
                        out_feat.SetField("WRS_Row", record.WRS_Row)
                        out_feat.SetField("Cloud_Cover", record.Cloud_Cover)
                        out_feat.SetField("Download_Path", record.Download_Path)
                        if record.ARDProduct:
                            out_feat.SetField("ARD_Path", record.ARDProduct_Path)
                        else:
                            out_feat.SetField("ARD_Path", "")
                        out_feat.SetField("North_Lat", record.North_Lat)
                        out_feat.SetField("South_Lat", record.South_Lat)
                        out_feat.SetField("East_Lon", record.East_Lon)
                        out_feat.SetField("West_Lon", record.West_Lon)
                        out_feat.SetGeometry(poly)
                        out_vec_lyr.CreateFeature(out_feat)
                        out_feat = None
            out_vec_lyr = None
            out_data_source = None
            db_ses.close()
        except Exception as e:
            raise e

    def reset_scn(self, unq_id, reset_download=False, reset_invalid=False):
        """
        A function which resets an image. This means any downloads and products are deleted
        and the database fields are reset to defaults. This allows the scene to be re-downloaded
        and processed.
        :param unq_id: unique id for the scene to be reset.
        :param reset_download: if True the download is deleted and reset in the database.
        """
        logger.debug("Creating Database Engine and Session.")
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()

        logger.debug("Perform query to find scene.")
        scn_record = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.PID == unq_id).one_or_none()

        if scn_record is None:
            ses.close()
            logger.error("PID {0} has not returned a scene - check inputs.".format(unq_id))
            raise EODataDownException("PID {0} has not returned a scene - check inputs.".format(unq_id))

        if scn_record.DCLoaded:
            # How to remove from datacube?
            scn_record.DCLoaded_Start_Date = None
            scn_record.DCLoaded_End_Date = None
            scn_record.DCLoaded = False

        if scn_record.ARDProduct:
            ard_path = scn_record.ARDProduct_Path
            if os.path.exists(ard_path):
                shutil.rmtree(ard_path)
            scn_record.ARDProduct_Start_Date = None
            scn_record.ARDProduct_End_Date = None
            scn_record.ARDProduct_Path = ""
            scn_record.ARDProduct = False

        if scn_record.Downloaded and reset_download:
            dwn_path = scn_record.Download_Path
            if os.path.exists(dwn_path):
                shutil.rmtree(dwn_path)
            scn_record.Download_Start_Date = None
            scn_record.Download_End_Date = None
            scn_record.Download_Path = ""
            scn_record.Downloaded = False

        if reset_invalid:
            scn_record.Invalid = False

        scn_record.ExtendedInfo = None
        flag_modified(scn_record, "ExtendedInfo")
        ses.add(scn_record)

        ses.commit()
        ses.close()

    def reset_dc_load(self, unq_id):
        """
        A function which resets whether an image has been loaded into a datacube
        (i.e., sets the flag to False).

        :param unq_id: unique id for the scene to be reset.
        
        """
        logger.debug("Creating Database Engine and Session.")
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()

        logger.debug("Perform query to find scene.")
        scn_record = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.PID == unq_id).one_or_none()

        if scn_record is None:
            ses.close()
            logger.error("PID {0} has not returned a scene - check inputs.".format(unq_id))
            raise EODataDownException("PID {0} has not returned a scene - check inputs.".format(unq_id))

        if scn_record.DCLoaded:
            # How to remove from datacube?
            scn_record.DCLoaded_Start_Date = None
            scn_record.DCLoaded_End_Date = None
            scn_record.DCLoaded = False

        ses.commit()
        ses.close()

    def get_sensor_summary_info(self):
        """
        A function which returns a dict of summary information for the sensor.
        For example, summary statistics for the download time, summary statistics
        for the file size, summary statistics for the ARD processing time.

        :return: dict of information.

        """
        import statistics
        info_dict = dict()
        logger.debug("Creating Database Engine and Session.")
        db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
        session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
        ses = session_sqlalc()

        logger.debug("Find the scene count.")
        vld_scn_count = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Invalid == False).count()
        invld_scn_count = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Invalid == True).count()
        dwn_scn_count = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Downloaded == True).count()
        ard_scn_count = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.ARDProduct == True).count()
        dcload_scn_count = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.DCLoaded == True).count()
        arch_scn_count = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Archived == True).count()
        info_dict['n_scenes'] = dict()
        info_dict['n_scenes']['n_valid_scenes'] = vld_scn_count
        info_dict['n_scenes']['n_invalid_scenes'] = invld_scn_count
        info_dict['n_scenes']['n_downloaded_scenes'] = dwn_scn_count
        info_dict['n_scenes']['n_ard_processed_scenes'] = ard_scn_count
        info_dict['n_scenes']['n_dc_loaded_scenes'] = dcload_scn_count
        info_dict['n_scenes']['n_archived_scenes'] = arch_scn_count
        logger.debug("Calculated the scene count.")

        logger.debug("Find the scene file sizes.")
        file_sizes = ses.query(EDDLandsat8EE.Total_Size).filter(EDDLandsat8EE.Invalid == False).all()
        if file_sizes is not None:
            if len(file_sizes) > 0:
                file_sizes_nums = list()
                for file_size in file_sizes:
                    if file_size[0] is not None:
                        file_sizes_nums.append(file_size[0])
                if len(file_sizes_nums) > 0:
                    total_file_size = sum(file_sizes_nums)
                    info_dict['file_size'] = dict()
                    info_dict['file_size']['file_size_total'] = total_file_size
                    if total_file_size > 0:
                        info_dict['file_size']['file_size_mean'] = statistics.mean(file_sizes_nums)
                        info_dict['file_size']['file_size_min'] = min(file_sizes_nums)
                        info_dict['file_size']['file_size_max'] = max(file_sizes_nums)
                        if len(file_sizes_nums) > 1:
                            info_dict['file_size']['file_size_stdev'] = statistics.stdev(file_sizes_nums)
                        info_dict['file_size']['file_size_median'] = statistics.median(file_sizes_nums)
                        if (len(file_sizes_nums) > 1) and (eodatadown.py_sys_version_flt >= 3.8):
                            info_dict['file_size']['file_size_quartiles'] = statistics.quantiles(file_sizes_nums)
        logger.debug("Calculated the scene file sizes.")

        logger.debug("Find download and processing time stats.")
        download_times = []
        ard_process_times = []
        scns = ses.query(EDDLandsat8EE).filter(EDDLandsat8EE.Downloaded == True)
        for scn in scns:
            download_times.append((scn.Download_End_Date - scn.Download_Start_Date).total_seconds())
            if scn.ARDProduct:
                ard_process_times.append((scn.ARDProduct_End_Date - scn.ARDProduct_Start_Date).total_seconds())

        if len(download_times) > 0:
            info_dict['download_time'] = dict()
            info_dict['download_time']['download_time_mean_secs'] = statistics.mean(download_times)
            info_dict['download_time']['download_time_min_secs'] = min(download_times)
            info_dict['download_time']['download_time_max_secs'] = max(download_times)
            if len(download_times) > 1:
                info_dict['download_time']['download_time_stdev_secs'] = statistics.stdev(download_times)
            info_dict['download_time']['download_time_median_secs'] = statistics.median(download_times)
            if (len(download_times) > 1) and (eodatadown.py_sys_version_flt >= 3.8):
                info_dict['download_time']['download_time_quartiles_secs'] = statistics.quantiles(download_times)

        if len(ard_process_times) > 0:
            info_dict['ard_process_time'] = dict()
            info_dict['ard_process_time']['ard_process_time_mean_secs'] = statistics.mean(ard_process_times)
            info_dict['ard_process_time']['ard_process_time_min_secs'] = min(ard_process_times)
            info_dict['ard_process_time']['ard_process_time_max_secs'] = max(ard_process_times)
            if len(ard_process_times) > 1:
                info_dict['ard_process_time']['ard_process_time_stdev_secs'] = statistics.stdev(ard_process_times)
            info_dict['ard_process_time']['ard_process_time_median_secs'] = statistics.median(ard_process_times)
            if (len(ard_process_times) > 1) and (eodatadown.py_sys_version_flt >= 3.8):
                info_dict['ard_process_time']['ard_process_time_quartiles_secs'] = statistics.quantiles(ard_process_times)
        logger.debug("Calculated the download and processing time stats.")

        if self.calc_scn_usr_analysis():
            plgin_lst = self.get_usr_analysis_keys()
            info_dict['usr_plugins'] = dict()
            for plgin_key in plgin_lst:
                info_dict['usr_plugins'][plgin_key] = dict()
                scns = ses.query(EDDLandsat8EEPlugins).filter(EDDLandsat8EEPlugins.PlugInName == plgin_key).all()
                n_err_scns = 0
                n_complete_scns = 0
                n_success_scns = 0
                plugin_times = []
                for scn in scns:
                    if scn.Completed:
                        plugin_times.append((scn.End_Date - scn.Start_Date).total_seconds())
                        n_complete_scns += 1
                    if scn.Success:
                        n_success_scns += 1
                    if scn.Error:
                        n_err_scns += 1
                info_dict['usr_plugins'][plgin_key]['n_success'] = n_success_scns
                info_dict['usr_plugins'][plgin_key]['n_completed'] = n_complete_scns
                info_dict['usr_plugins'][plgin_key]['n_error'] = n_err_scns
                if len(plugin_times) > 0:
                    info_dict['usr_plugins'][plgin_key]['processing'] = dict()
                    info_dict['usr_plugins'][plgin_key]['processing']['time_mean_secs'] = statistics.mean(plugin_times)
                    info_dict['usr_plugins'][plgin_key]['processing']['time_min_secs'] = min(plugin_times)
                    info_dict['usr_plugins'][plgin_key]['processing']['time_max_secs'] = max(plugin_times)
                    if len(plugin_times) > 1:
                        info_dict['usr_plugins'][plgin_key]['processing']['time_stdev_secs'] = statistics.stdev(plugin_times)
                    info_dict['usr_plugins'][plgin_key]['processing']['time_median_secs'] = statistics.median(plugin_times)
                    if (len(plugin_times) > 1) and (eodatadown.py_sys_version_flt >= 3.8):
                        info_dict['usr_plugins'][plgin_key]['processing']['time_quartiles_secs'] = statistics.quantiles(plugin_times)
        ses.close()
        return info_dict

    def get_sensor_plugin_info(self, plgin_key):
        """
        A function which generates a dictionary of information (e.g., errors) for a plugin.

        :param plgin_key: The name of the plugin for which the information will be produced.
        :return: a dict with the information.

        """
        info_dict = dict()
        if self.calc_scn_usr_analysis():
            plugin_keys = self.get_usr_analysis_keys()
            if plgin_key not in plugin_keys:
                raise EODataDownException("The specified plugin ('{}') does not exist.".format(plgin_key))

            import statistics
            logger.debug("Creating Database Engine and Session.")
            db_engine = sqlalchemy.create_engine(self.db_info_obj.dbConn)
            session_sqlalc = sqlalchemy.orm.sessionmaker(bind=db_engine)
            ses = session_sqlalc()
            scns = ses.query(EDDLandsat8EEPlugins).filter(EDDLandsat8EEPlugins.PlugInName == plgin_key).all()
            n_err_scns = 0
            n_complete_scns = 0
            n_success_scns = 0
            plugin_times = []
            errors_dict = dict()
            for scn in scns:
                if scn.Completed:
                    plugin_times.append((scn.End_Date - scn.Start_Date).total_seconds())
                    n_complete_scns += 1
                if scn.Success:
                    n_success_scns += 1
                if scn.Error:
                    n_err_scns += 1
                    errors_dict[scn.Scene_PID] = scn.ExtendedInfo
            ses.close()
            info_dict[plgin_key] = dict()
            info_dict[plgin_key]['n_success'] = n_success_scns
            info_dict[plgin_key]['n_completed'] = n_complete_scns
            info_dict[plgin_key]['n_error'] = n_err_scns
            if len(plugin_times) > 0:
                info_dict[plgin_key]['processing'] = dict()
                info_dict[plgin_key]['processing']['time_mean_secs'] = statistics.mean(plugin_times)
                info_dict[plgin_key]['processing']['time_min_secs'] = min(plugin_times)
                info_dict[plgin_key]['processing']['time_max_secs'] = max(plugin_times)
                if len(plugin_times) > 1:
                    info_dict[plgin_key]['processing']['time_stdev_secs'] = statistics.stdev(plugin_times)
                info_dict[plgin_key]['processing']['time_median_secs'] = statistics.median(plugin_times)
                if (len(plugin_times) > 1) and (eodatadown.py_sys_version_flt >= 3.8):
                    info_dict[plgin_key]['processing']['time_quartiles_secs'] = statistics.quantiles(plugin_times)
            if n_err_scns > 0:
                info_dict[plgin_key]['errors'] = errors_dict
        else:
            raise EODataDownException("There are no plugins for a summary to be produced for.")

        return info_dict