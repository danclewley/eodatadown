#!/usr/bin/env python
"""
EODataDown - a sensor class for Sentinel-2 data downloaded from the Google Cloud.
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
# Purpose:  Provides a sensor class for Sentinel-2 data downloaded from the Google Cloud.
#
# Author: Pete Bunting
# Email: pfb@aber.ac.uk
# Date: 07/08/2018
# Version: 1.0
#
# History:
# Version 1.0 - Created.

import logging
import json
import os
import os.path
import datetime
import multiprocessing
import shutil
import rsgislib

import eodatadown.eodatadownutils
from eodatadown.eodatadownutils import EODataDownException
from eodatadown.eodatadownsensor import EODataDownSensor
from eodatadown.eodatadownusagedb import EODataDownUpdateUsageLogDB
import eodatadown.eodatadownrunarcsi

from sqlalchemy.ext.declarative import declarative_base
import sqlalchemy

logger = logging.getLogger(__name__)

Base = declarative_base()

class EDDSentinel2Google(Base):
    __tablename__ = "EDDSentinel2Google"

    PID = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    Granule_ID = sqlalchemy.Column(sqlalchemy.String, nullable=False)
    Product_ID = sqlalchemy.Column(sqlalchemy.String, nullable=True)
    Datatake_Identifier = sqlalchemy.Column(sqlalchemy.String, nullable=True)
    Mgrs_Tile = sqlalchemy.Column(sqlalchemy.String, nullable=True)
    Sensing_Time = sqlalchemy.Column(sqlalchemy.Date, nullable=True)
    Geometric_Quality_Flag = sqlalchemy.Column(sqlalchemy.String, nullable=True)
    Generation_Time = sqlalchemy.Column(sqlalchemy.DateTime, nullable=False)
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
    ARDProduct_Start_Date = sqlalchemy.Column(sqlalchemy.DateTime, nullable=True)
    ARDProduct_End_Date = sqlalchemy.Column(sqlalchemy.DateTime, nullable=True)
    ARDProduct = sqlalchemy.Column(sqlalchemy.Boolean, nullable=False, default=False)
    ARDProduct_Path = sqlalchemy.Column(sqlalchemy.String, nullable=False, default="")

def _download_scn_goog(params):
    """
    Function which is used with multiprocessing pool object for downloading landsat data from Google.
    :param params:
    :return:
    """
    granule_id = params[0]
    dbInfoObj = params[1]
    googKeyJSON = params[2]
    googProjName = params[3]
    bucket_name = params[4]
    scn_dwnlds_filelst = params[5]
    scn_lcl_dwnld_path = params[6]

    logger.debug("Set up Google storage API.")
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = googKeyJSON
    os.environ["GOOGLE_CLOUD_PROJECT"] = googProjName
    from google.cloud import storage
    storage_client = storage.Client()
    bucket_obj = storage_client.get_bucket(bucket_name)

    logger.info("Downloading "+granule_id)
    start_date = datetime.datetime.now()
    for dwnld in scn_dwnlds_filelst:
        blob_obj = bucket_obj.blob(dwnld["bucket_path"])
        blob_obj.download_to_filename(dwnld["dwnld_path"])
    end_date = datetime.datetime.now()
    logger.info("Finished Downloading " + granule_id)

    logger.debug("Set up database connection and update record.")
    dbEng = sqlalchemy.create_engine(dbInfoObj.dbConn)
    Session = sqlalchemy.orm.sessionmaker(bind=dbEng)
    ses = Session()
    query_result = ses.query(EDDSentinel2Google).filter(EDDSentinel2Google.Granule_ID == granule_id).one_or_none()
    if query_result is None:
        logger.error("Could not find the scene within local database: " + granule_id)
    query_result.Downloaded = True
    query_result.Download_Start_Date = start_date
    query_result.Download_End_Date = end_date
    query_result.Download_Path = scn_lcl_dwnld_path
    ses.commit()
    ses.close()
    logger.debug("Finished download and updated database.")


def _process_to_ard(params):
    """
    A function which is used with the python multiprocessing pool feature to convert a scene to an ARD product
    using multiple processing cores.
    :param params:
    :return:
    """
    granule_id = params[0]
    dbInfoObj = params[1]
    scn_path = params[2]
    dem_file = params[3]
    output_dir = params[4]
    tmp_dir = params[5]
    final_ard_path = params[6]
    reproj_outputs = params[7]
    proj_wkt_file = params[8]
    projabbv = params[9]

    eddUtils = eodatadown.eodatadownutils.EODataDownUtils()
    input_hdr = eddUtils.findFile(scn_path, "*MTD*.xml")

    start_date = datetime.datetime.now()
    eodatadown.eodatadownrunarcsi.run_arcsi_sentinel2(input_hdr, dem_file, output_dir, tmp_dir, reproj_outputs, proj_wkt_file, projabbv)

    logger.debug("Move final ARD files to specified location.")
    # Move ARD files to be kept.
    eodatadown.eodatadownrunarcsi.move_arcsi_products(output_dir, final_ard_path)
    # Remove Remaining files.
    shutil.rmtree(output_dir)
    shutil.rmtree(tmp_dir)
    logger.debug("Moved final ARD files to specified location.")
    end_date = datetime.datetime.now()

    logger.debug("Set up database connection and update record.")
    dbEng = sqlalchemy.create_engine(dbInfoObj.dbConn)
    Session = sqlalchemy.orm.sessionmaker(bind=dbEng)
    ses = Session()
    query_result = ses.query(EDDSentinel2Google).filter(EDDSentinel2Google.Granule_ID == granule_id).one_or_none()
    if query_result is None:
        logger.error("Could not find the scene within local database: " + granule_id)
    query_result.ARDProduct = True
    query_result.ARDProduct_Start_Date = start_date
    query_result.ARDProduct_End_Date = end_date
    query_result.ARDProduct_Path = final_ard_path
    ses.commit()
    ses.close()
    logger.debug("Finished download and updated database.")


class EODataDownSentinel2GoogSensor (EODataDownSensor):
    """
    An class which represents a the Sentinel-2 sensor being downloaded from the Google Cloud.
    """

    def __init__(self, dbInfoObj):
        EODataDownSensor.__init__(self, dbInfoObj)
        self.sensorName = "Sentinel2GOOG"

    def parseSensorConfig(self, config_file,  first_parse=False):
        """
        A function to parse the Sentinel2GOOG JSON config file.
        :param config_file:
        :param first_parse:
        :return:
        """
        eddFileChecker = eodatadown.eodatadownutils.EDDCheckFileHash()
        # If it is the first time the config_file is parsed then create the signature file.
        if first_parse:
            eddFileChecker.createFileSig(config_file)
            logger.debug("Created signature file for config file.")

        if not eddFileChecker.checkFileSig(config_file):
            raise EODataDownException("Input config did not match the file signature.")

        with open(config_file) as f:
            config_data = json.load(f)
            json_parse_helper = eodatadown.eodatadownutils.EDDJSONParseHelper()
            logger.debug("Testing config file is for 'Sentinel2GOOG'")
            json_parse_helper.getStrValue(config_data, ["eodatadown", "sensor", "name"], [self.sensorName])
            logger.debug("Have the correct config file for 'Sentinel2GOOG'")

            logger.debug("Find ARD processing params from config file")
            self.demFile = json_parse_helper.getStrValue(config_data, ["eodatadown", "sensor", "ardparams", "dem"])
            self.projEPSG = -1
            self.projabbv = ""
            self.ardProjDefined = False
            if json_parse_helper.doesPathExist(config_data, ["eodatadown", "sensor", "ardparams", "proj"]):
                self.ardProjDefined = True
                self.projabbv = json_parse_helper.getStrValue(config_data, ["eodatadown", "sensor", "ardparams", "proj", "projabbv"])
                self.projEPSG = int(json_parse_helper.getNumericValue(config_data, ["eodatadown", "sensor", "ardparams", "proj", "epsg"], 0, 1000000000))
            logger.debug("Found ARD processing params from config file")

            logger.debug("Find paths from config file")
            self.baseDownloadPath = json_parse_helper.getStrValue(config_data, ["eodatadown", "sensor", "paths", "download"])
            self.ardProdWorkPath = json_parse_helper.getStrValue(config_data, ["eodatadown", "sensor", "paths", "ardwork"])
            self.ardFinalPath = json_parse_helper.getStrValue(config_data, ["eodatadown", "sensor", "paths", "ardfinal"])
            self.ardProdTmpPath = json_parse_helper.getStrValue(config_data, ["eodatadown", "sensor", "paths", "ardtmp"])
            logger.debug("Found paths from config file")

            logger.debug("Find search params from config file")
            self.s2Granules = json_parse_helper.getStrListValue(config_data, ["eodatadown", "sensor", "download", "granules"])
            self.cloudCoverThres = json_parse_helper.getNumericValue(config_data, ["eodatadown", "sensor", "download", "cloudcover"], 0, 100)
            self.startDate = json_parse_helper.getDateValue(config_data, ["eodatadown", "sensor", "download", "startdate"], "%Y-%m-%d")
            logger.debug("Found search params from config file")

            logger.debug("Find Google Account params from config file")
            self.googProjName = json_parse_helper.getStrValue(config_data, ["eodatadown", "sensor", "googleinfo", "projectname"])
            self.googKeyJSON = json_parse_helper.getStrValue(config_data, ["eodatadown", "sensor", "googleinfo", "googlejsonkey"])
            logger.debug("Found Google Account params from config file")


    def initSensorDB(self):
        """
        Initialise the sensor database table.
        :return:
        """
        logger.debug("Creating Database Engine.")
        dbEng = sqlalchemy.create_engine(self.dbInfoObj.dbConn)

        logger.debug("Drop system table if within the existing database.")
        Base.metadata.drop_all(dbEng)

        logger.debug("Creating Sentinel2GOOG Database.")
        Base.metadata.bind = dbEng
        Base.metadata.create_all()

    def check4NewData(self):
        """
        A function which queries the Google Sentinel-2 BigQuery database (link below) and builds a local
        database for the row/paths specified. If data already exists within the database then a query
        will be run from the last acquisition date within the database to present.

        https://bigquery.cloud.google.com/table/bigquery-public-data:cloud_storage_geo_index.sentinel_2_index
        :return:
        """
        logger.info("Checking for new data... 'Sentinel2GOOG'")
        logger.debug("Export Google Environmental Variable.")
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = self.googKeyJSON
        os.environ["GOOGLE_CLOUD_PROJECT"] = self.googProjName
        from google.cloud import bigquery
        client = bigquery.Client()
        job_config = bigquery.QueryJobConfig()
        job_config.use_legacy_sql = True

        logger.debug("Creating Database Engine and Session.")
        dbEng = sqlalchemy.create_engine(self.dbInfoObj.dbConn)
        Session = sqlalchemy.orm.sessionmaker(bind=dbEng)
        ses = Session()

        logger.debug("Find the start date for query - if table is empty then using config date otherwise date of last acquried image.")
        query_date = self.startDate
        if ses.query(EDDSentinel2Google).first() is not None:
            query_date = ses.query(EDDSentinel2Google).order_by(EDDSentinel2Google.Sensing_Time.desc()).first().Sensing_Time
        logger.info("Query with start at date: "+str(query_date))

        logger.debug("Perform google query...")
        goog_fields = "granule_id,product_id,datatake_identifier,mgrs_tile,sensing_time,geometric_quality_flag," \
                      "generation_time,north_lat,south_lat,west_lon,east_lon,base_url,total_size,cloud_cover"
        goog_db_str = "[bigquery-public-data.cloud_storage_geo_index.sentinel_2_index]"

        goog_filter_date = "sensing_time > '"+query_date.strftime("%Y-%m-%dT%H:%M:%S")+"'"
        goog_filter_cloud = "FLOAT(cloud_cover) < "+str(self.cloudCoverThres)

        goog_filter = goog_filter_date + " AND " + goog_filter_cloud

        new_scns_avail = False
        for granule_str in self.s2Granules:
            logger.info("Finding scenes for granule: "+granule_str)
            granule_filter = "mgrs_tile = \""+granule_str+"\""
            goog_query = "SELECT " + goog_fields + " FROM " + goog_db_str + " WHERE " + goog_filter + " AND " + granule_filter
            logger.debug("Query: '"+goog_query+"'")
            query_results = client.query(goog_query, job_config=job_config)
            logger.debug("Performed google query")

            logger.debug("Process google query result and add to local database (Granule: "+granule_str+")")
            if query_results.result():
                db_records = []
                for row in query_results.result():
                    query_rtn = ses.query(EDDSentinel2Google).filter(EDDSentinel2Google.Granule_ID==row.granule_id).one_or_none()
                    if query_rtn is None:
                        logger.debug("Granule_ID: "+row.granule_id+"\tProduct_ID: "+row.product_id)
                        sensing_time_tmp = row.sensing_time.replace('Z', '')[:-1]
                        generation_time_tmp = row.generation_time.replace('Z', '')[:-1]
                        db_records.append(
                            EDDSentinel2Google(Granule_ID=row.granule_id, Product_ID=row.product_id,
                                               Datatake_Identifier=row.datatake_identifier, Mgrs_Tile=row.mgrs_tile,
                                               Sensing_Time=datetime.datetime.strptime(sensing_time_tmp, "%Y-%m-%dT%H:%M:%S.%f"),
                                               Geometric_Quality_Flag=row.geometric_quality_flag,
                                               Generation_Time=datetime.datetime.strptime(generation_time_tmp, "%Y-%m-%dT%H:%M:%S.%f"),
                                               Cloud_Cover=float(row.cloud_cover), North_Lat=row.north_lat, South_Lat=row.south_lat,
                                               East_Lon=row.east_lon, West_Lon=row.west_lon, Total_Size=row.total_size,
                                               Remote_URL=row.base_url, Query_Date=datetime.datetime.now(),
                                               Download_Start_Date=None, Download_End_Date=None, Downloaded=False,
                                               Download_Path="", ARDProduct_Start_Date=None, ARDProduct_End_Date=None,
                                               ARDProduct=False, ARDProduct_Path=""))
                if len(db_records) > 0:
                    ses.add_all(db_records)
                    ses.commit()
                    new_scns_avail = True
            logger.debug("Processed google query result and added to local database (Granule: "+granule_str+")")

        ses.close()
        logger.debug("Closed Database session")
        edd_usage_db = EODataDownUpdateUsageLogDB(self.dbInfoObj)
        edd_usage_db.addEntry(description_val="Checked for availability of new scenes", sensor_val=self.sensorName, updated_lcl_db=True, scns_avail=new_scns_avail)

    def downloadNewData(self, ncores):
        """
        A function which downloads the scenes which are within the database but not downloaded.
        :param ncores:
        :return:
        """
        logger.debug("Import Google storage module and create storage object.")
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = self.googKeyJSON
        os.environ["GOOGLE_CLOUD_PROJECT"] = self.googProjName
        from google.cloud import storage
        storage_client = storage.Client()

        logger.debug("Creating Database Engine and Session.")
        dbEng = sqlalchemy.create_engine(self.dbInfoObj.dbConn)
        Session = sqlalchemy.orm.sessionmaker(bind=dbEng)
        ses = Session()

        logger.debug("Perform query to find scenes which need downloading.")
        query_result = ses.query(EDDSentinel2Google).filter(EDDSentinel2Google.Downloaded==False).all()

        if query_result is not None:
            logger.debug("Create the output directory for this download.")
            dt_obj = datetime.datetime.now()
            lcl_dwnld_path = os.path.join(self.baseDownloadPath, dt_obj.strftime("%Y-%m-%d"))
            if not os.path.exists(lcl_dwnld_path):
                os.mkdir(lcl_dwnld_path)

            logger.debug("Build download file list.")
            dwnld_params = []
            for record in query_result:
                logger.debug("Building download info for '"+record.Remote_URL+"'")
                url_path = record.Remote_URL
                url_path = url_path.replace("gs://", "")
                url_path_parts = url_path.split("/")
                bucket_name = url_path_parts[0]
                if bucket_name != "gcp-public-data-sentinel-2":
                    logger.error("Incorrect bucket name '"+bucket_name+"'")
                    raise EODataDownException("The bucket specified in the URL is not the Google Public Sentinel-2 Bucket - something has gone wrong.")
                bucket_prefix = url_path.replace(bucket_name+"/", "")
                dwnld_out_dirname = url_path_parts[-1]
                scn_lcl_dwnld_path = os.path.join(lcl_dwnld_path, dwnld_out_dirname)
                if not os.path.exists(scn_lcl_dwnld_path):
                    os.mkdir(scn_lcl_dwnld_path)

                logger.debug("Get the storage bucket and blob objects.")
                bucket_obj = storage_client.get_bucket(bucket_name)
                bucket_blobs = bucket_obj.list_blobs(prefix=bucket_prefix)
                scn_dwnlds_filelst = []
                for blob in bucket_blobs:
                    if "$folder$" in blob.name:
                        continue
                    scnfilename = blob.name.replace(bucket_prefix+"/", "")
                    dwnld_file = os.path.join(scn_lcl_dwnld_path, scnfilename)
                    dwnld_dirpath = os.path.split(dwnld_file)[0]
                    if not os.path.exists(dwnld_dirpath):
                        os.makedirs(dwnld_dirpath, exist_ok=True)
                    scn_dwnlds_filelst.append({"bucket_path":blob.name, "dwnld_path": dwnld_file})

                dwnld_params.append([record.Granule_ID, self.dbInfoObj, self.googKeyJSON, self.googProjName, bucket_name, scn_dwnlds_filelst, scn_lcl_dwnld_path])
        else:
            logger.info("There are no scenes to be downloaded.")
        ses.close()
        logger.debug("Closed the database session.")

        logger.info("Start downloading the scenes.")
        with multiprocessing.Pool(processes=ncores) as pool:
            pool.map(_download_scn_goog, dwnld_params)
        logger.info("Finished downloading the scenes.")
        edd_usage_db = EODataDownUpdateUsageLogDB(self.dbInfoObj)
        edd_usage_db.addEntry(description_val="Checked downloaded new scenes.", sensor_val=self.sensorName, updated_lcl_db=True, downloaded_new_scns=True)

    def convertNewData2ARD(self, ncores):
        """
        A function to convert the available scenes to an ARD product using ARCSI.
        :param ncores:
        :return:
        """
        if not os.path.exists(self.ardFinalPath):
            raise EODataDownException("The ARD final path does not exist, please create and run again.")

        if not os.path.exists(self.ardProdWorkPath):
            raise EODataDownException("The ARD working path does not exist, please create and run again.")

        if not os.path.exists(self.ardProdTmpPath):
            raise EODataDownException("The ARD tmp path does not exist, please create and run again.")

        logger.debug("Creating Database Engine and Session.")
        dbEng = sqlalchemy.create_engine(self.dbInfoObj.dbConn)
        Session = sqlalchemy.orm.sessionmaker(bind=dbEng)
        ses = Session()

        logger.debug("Perform query to find scenes which need converting to ARD.")
        query_result = ses.query(EDDSentinel2Google).filter(EDDSentinel2Google.Downloaded == True, EDDSentinel2Google.ARDProduct == False).all()

        proj_wkt_file = None
        if self.ardProjDefined:
            rsgis_utils = rsgislib.RSGISPyUtils()
            proj_wkt = rsgis_utils.getWKTFromEPSGCode(self.projEPSG)

        if query_result is not None:
            logger.debug("Create the specific output directories for the ARD processing.")
            dt_obj = datetime.datetime.now()
            final_ard_path = os.path.join(self.ardFinalPath, dt_obj.strftime("%Y-%m-%d"))
            if not os.path.exists(final_ard_path):
                os.mkdir(final_ard_path)

            work_ard_path = os.path.join(self.ardProdWorkPath, dt_obj.strftime("%Y-%m-%d"))
            if not os.path.exists(work_ard_path):
                os.mkdir(work_ard_path)

            tmp_ard_path = os.path.join(self.ardProdTmpPath, dt_obj.strftime("%Y-%m-%d"))
            if not os.path.exists(tmp_ard_path):
                os.mkdir(tmp_ard_path)

            ard_params = []
            for record in query_result:
                logger.debug("Create info for running ARD analysis for scene: " + record.Granule_ID)
                final_ard_scn_path = os.path.join(final_ard_path, record.Product_ID)
                if not os.path.exists(final_ard_scn_path):
                    os.mkdir(final_ard_scn_path)

                work_ard_scn_path = os.path.join(work_ard_path, record.Product_ID)
                if not os.path.exists(work_ard_scn_path):
                    os.mkdir(work_ard_scn_path)

                tmp_ard_scn_path = os.path.join(tmp_ard_path, record.Product_ID)
                if not os.path.exists(tmp_ard_scn_path):
                    os.mkdir(tmp_ard_scn_path)

                if self.ardProjDefined:
                    proj_wkt_file = os.path.join(work_ard_scn_path, record.Product_ID+"_wkt.wkt")
                    rsgis_utils.writeList2File([proj_wkt], proj_wkt_file)

                ard_params.append([record.Granule_ID, self.dbInfoObj, record.Download_Path, self.demFile, work_ard_scn_path, tmp_ard_scn_path, final_ard_scn_path, self.ardProjDefined, proj_wkt_file, self.projabbv])
        else:
            logger.info("There are no scenes which have been downloaded but not processed to an ARD product.")
        ses.close()
        logger.debug("Closed the database session.")

        logger.info("Start processing the scenes.")
        with multiprocessing.Pool(processes=ncores) as pool:
            pool.map(_process_to_ard, ard_params)
        logger.info("Finished processing the scenes.")

        edd_usage_db = EODataDownUpdateUsageLogDB(self.dbInfoObj)
        edd_usage_db.addEntry(description_val="Processed scenes to an ARD product.", sensor_val=self.sensorName, updated_lcl_db=True, convert_scns_ard=True)
