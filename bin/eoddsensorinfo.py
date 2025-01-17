#!/usr/bin/env python
"""
EODataDown - Create sensor information/statistics
"""
# This file is part of 'EODataDown'
# A tool for automating Earth Observation Data Downloading.
#
# Copyright 2020 Pete Bunting
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
# Purpose:  Command line tool for running the system.
#
# Author: Pete Bunting
# Email: pfb@aber.ac.uk
# Date: 30/05/2020
# Version: 1.0
#
# History:
# Version 1.0 - Created.

import eodatadown.eodatadownrun
import argparse
import logging
import os
import os.path
import rsgislib

from eodatadown import EODATADOWN_SENSORS_LIST

logger = logging.getLogger('eoddsensorinfo.py')

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", type=str, default="", help="Path to the JSON config file.")
    parser.add_argument("-s", "--sensor", type=str, required=True, choices=EODATADOWN_SENSORS_LIST,
                        help='''Specify the sensor for which this process should be executed.''')
    parser.add_argument("-o", "--output", type=str, required=False, help="Output JSON file with sensor report."
                                                                         "Optional. If not provided report is "
                                                                         "written to the console.")
    args = parser.parse_args()

    config_file = args.config
    sys_config_value = os.getenv('EDD_SYS_CFG', None)
    if (config_file == '') and (sys_config_value is not None):
        config_file = sys_config_value
        print("Using system config file: '{}'".format(config_file))

    if not os.path.exists(config_file):
        logger.info("The config file does not exist: '" + config_file + "'")
        raise Exception("Config file does not exist")

    t = rsgislib.RSGISTime()
    t.start(True)

    logger.info('Running process to get sensor report for {}'.format(args.sensor))
    eodatadown.eodatadownrun.gen_sensor_summary_report(config_file, args.sensor, args.output)
    logger.info('Finished process to get sensor report for {}'.format(args.sensor))

    t.end(reportDiff=True, preceedStr='EODataDown processing completed ', postStr=' - eoddsensorinfo.py.')

