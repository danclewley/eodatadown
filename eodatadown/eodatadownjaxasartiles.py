#!/usr/bin/env python
"""
EODataDown - a sensor class for downloading JAXA SAR tiles.
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
# Purpose:  Provides an abstract sensor class.
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
import os.path

import eodatadown.eodatadownutils
from eodatadown.eodatadownutils import EODataDownException
from eodatadown.eodatadownutils import EODataDownResponseException
from eodatadown.eodatadownsensor import EODataDownSensor
from eodatadown.eodatadownusagedb import EODataDownUpdateUsageLogDB


from sqlalchemy.ext.declarative import declarative_base
import sqlalchemy

logger = logging.getLogger(__name__)

Base = declarative_base()


class EDDJAXASARTiles(Base):
    __tablename__ = "EDDJAXASARTiles"

    PID = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, autoincrement=True)
    Tile_Name = sqlalchemy.Column(sqlalchemy.String, nullable=False)
    Parent_Tile = sqlalchemy.Column(sqlalchemy.String, nullable=False)
    Year = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)
    File_Name = sqlalchemy.Column(sqlalchemy.String, nullable=False)
    Server_File_Path = sqlalchemy.Column(sqlalchemy.String, nullable=False)
    InstrumentName = sqlalchemy.Column(sqlalchemy.String, nullable=False)
    Start_Date = sqlalchemy.Column(sqlalchemy.DateTime, nullable=True)
    End_Date = sqlalchemy.Column(sqlalchemy.DateTime, nullable=True)
    Incident_Angle_Low = sqlalchemy.Column(sqlalchemy.Float, nullable=True)
    Incident_Angle_High = sqlalchemy.Column(sqlalchemy.Float, nullable=True)
    North_Lat = sqlalchemy.Column(sqlalchemy.Float, nullable=True)
    South_Lat = sqlalchemy.Column(sqlalchemy.Float, nullable=True)
    East_Lon = sqlalchemy.Column(sqlalchemy.Float, nullable=True)
    West_Lon = sqlalchemy.Column(sqlalchemy.Float, nullable=True)
    Remote_URL = sqlalchemy.Column(sqlalchemy.String, nullable=True)
    Remote_URL_MD5 = sqlalchemy.Column(sqlalchemy.String, nullable=True)
    Total_Size = sqlalchemy.Column(sqlalchemy.Integer, nullable=True)
    Query_Date = sqlalchemy.Column(sqlalchemy.DateTime, nullable=False)
    Download_Start_Date = sqlalchemy.Column(sqlalchemy.DateTime, nullable=True)
    Download_End_Date = sqlalchemy.Column(sqlalchemy.DateTime, nullable=True)
    Downloaded = sqlalchemy.Column(sqlalchemy.Boolean, nullable=False, default=False)
    Download_Path = sqlalchemy.Column(sqlalchemy.String, nullable=False, default="")
    ARDProduct_Start_Date = sqlalchemy.Column(sqlalchemy.DateTime, nullable=True)
    ARDProduct_End_Date = sqlalchemy.Column(sqlalchemy.DateTime, nullable=True)
    ARDProduct = sqlalchemy.Column(sqlalchemy.Boolean, nullable=False, default=False)
    ARDProduct_Path = sqlalchemy.Column(sqlalchemy.String, nullable=False, default="")


class EDDJAXASARYear(Base):
    __tablename__ = "EDDJAXASARYear"

    Year = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True, nullable=False)
    Complete = sqlalchemy.Column(sqlalchemy.Boolean, nullable=False, default=False)


class EODataDownJAXASARTileSensor (EODataDownSensor):
    """
    An abstract class which represents a sensor and defines the functions a sensor must have.
    """

    def __init__(self, dbInfoObj):
        self.sensorName = "JAXASARTiles"
        self.dbInfoObj = dbInfoObj
        self.avail_years = [1996, 2007, 2008, 2009, 2010, 2015, 2016, 2017]
        self.jaxa_ftp = "ftp.eorc.jaxa.jp"
        self.ftp_paths = dict()
        self.ftp_paths[1996] = "/pub/ALOS-2/JERS-1_MSC/25m_MSC/1996/"
        self.ftp_paths[2007] = "/pub/ALOS/ext1/PALSAR_MSC/25m_MSC/2007"
        self.ftp_paths[2008] = "/pub/ALOS/ext1/PALSAR_MSC/25m_MSC/2008"
        self.ftp_paths[2009] = "/pub/ALOS/ext1/PALSAR_MSC/25m_MSC/2009"
        self.ftp_paths[2010] = "/pub/ALOS/ext1/PALSAR_MSC/25m_MSC/2010"
        self.ftp_paths[2015] = "/pub/ALOS-2/ext1/PALSAR-2_MSC/25m_MSC/2015"
        self.ftp_paths[2016] = "/pub/ALOS-2/ext1/PALSAR-2_MSC/25m_MSC/2016"
        self.ftp_paths[2017] = "/pub/ALOS-2/ext2/PALSAR-2_MSC/25m_MSC/2017"

    def getSensorName(self):
        return self.sensorName

    def parseSensorConfig(self, config_file, first_parse=False):
        """
        A function to parse the JAXASARTiles JSON config file.
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
            logger.debug("Testing config file is for 'JAXASARTiles'")
            json_parse_helper.getStrValue(config_data, ["eodatadown", "sensor", "name"], [self.sensorName])
            logger.debug("Have the correct config file for 'JAXASARTiles'")

            logger.debug("Find ARD processing params from config file")
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
            self.tile_lst = json_parse_helper.getListValue(config_data, ["eodatadown", "sensor", "download", "tiles"])
            self.all_jaxa_tiles = False
            if len(self.tile_lst) == 0:
                self.all_jaxa_tiles = True

            self.years_of_interest = json_parse_helper.getListValue(config_data, ["eodatadown", "sensor", "download", "years"])
            if len(self.years_of_interest) == 0:
                raise EODataDownException("Must specify at least one year")

            for year in self.years_of_interest:
                if year not in self.avail_years:
                    raise EODataDownException("The year ({0}) specified is not within the list of available years.".format(year))
            logger.debug("Found search params from config file")

    def initSensorDB(self):
        """
        Initialise the sensor database table.
        :return:
        """
        logger.debug("Creating Database Engine.")
        dbEng = sqlalchemy.create_engine(self.dbInfoObj.dbConn)

        logger.debug("Drop system table if within the existing database.")
        Base.metadata.drop_all(dbEng)

        logger.debug("Creating JAXASARTiles Database.")
        Base.metadata.bind = dbEng
        Base.metadata.create_all()

    def check4NewData(self):
        """

        :return:
        """
        logger.debug("Creating Database Engine and Session.")
        dbEng = sqlalchemy.create_engine(self.dbInfoObj.dbConn)
        Session = sqlalchemy.orm.sessionmaker(bind=dbEng)
        ses = Session()

        query_rtn = ses.query(EDDJAXASARTiles.Year).group_by(EDDJAXASARTiles.Year).all()
        years_in_db = []
        for result in query_rtn:
            years_in_db.append(result[0])

        years_to_dwn = []
        for year_tmp in self.years_of_interest:
            if year_tmp not in years_in_db:
                years_to_dwn.append(year_tmp)

        print(years_to_dwn)
        if len(years_to_dwn) > 0:
            edd_ftp_utils = eodatadown.eodatadownutils.EODDFTPDownload()
            new_scns_avail = False
            for cyear in years_to_dwn:
                query_rtn = ses.query(EDDJAXASARYear).filter(EDDJAXASARYear.Year == cyear).one_or_none()
                if query_rtn is None:
                    eddSARYearObj = EDDJAXASARYear(Year=cyear)
                    ses.add(eddSARYearObj)
                    ses.commit()
                eddSARYearObj = query_rtn
                file_lst = edd_ftp_utils.getFTPFileListings(self.jaxa_ftp, self.ftp_paths[cyear], "", "", ftp_timeout=None)
                db_records = []
                for file_path in file_lst:
                    file_base_path = os.path.split(file_path)[0]
                    parent_tile = os.path.basename(file_base_path)
                    file_name = os.path.split(file_path)[1]
                    tile_name = file_name.split("_")[0]
                    if "FNF" not in file_name:
                        db_records.append(EDDJAXASARTiles(Tile_Name=tile_name, Parent_Tile=parent_tile, Year=cyear, File_Name=file_name, Server_File_Path=file_path))
                eddSARYearObj.Complete = True
                ses.commit()
                if len(db_records) > 0:
                    ses.add_all(db_records)
                    ses.commit()
                    new_scns_avail = True
        ses.close()
        logger.debug("Closed Database session")
        edd_usage_db = EODataDownUpdateUsageLogDB(self.dbInfoObj)
        edd_usage_db.addEntry(description_val="Checked for availability of new scenes", sensor_val=self.sensorName, updated_lcl_db=True, scns_avail=new_scns_avail)

    def downloadNewData(self, ncores):
        """

        :param ncores:
        :return:
        """
        raise EODataDownException("Not implemented")


    def convertNewData2ARD(self, ncores):
        """

        :param ncores:
        :return:
        """
        raise EODataDownException("Not implemented")