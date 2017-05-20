'''
/*
 * Copyright 2010-2016 Amazon.com, Inc. or its affiliates. All Rights Reserved.
 *
 * Licensed under the Apache License, Version 2.0 (the "License").
 * You may not use this file except in compliance with the License.
 * A copy of the License is located at
 *
 *  http://aws.amazon.com/apache2.0
 *
 * or in the "license" file accompanying this file. This file is distributed
 * on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
 * express or implied. See the License for the specific language governing
 * permissions and limitations under the License.
 */
 '''

# drag in the SDK from two dirs up
import sys
sys.path.append("./aws-iot-device-sdk-python")
from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTShadowClient

import os
import threading
import logging
import time
import json
import getopt

class Device(object):
    def __init__(self):
        self._shadowName = "<<UNNAMEDDEVICE>>"

    def shadowDeltaChangeHandler(self, payload, responseStatus, token):
        print("received delta: " + payload)

    def shadowUpdateCompleteHandler(self, payload, responseStatus, token):
        print("shadow update completed: " + payload)
    
    def shadowDeleteCompleteHandler(self, payload, responseStatus, token):
        print("shadow delete completed: " + payload)
        # test if we can still push
        JSONPayload = '{"state":{"desired":{"property": 42}}}'
        self._deviceShadow.shadowUpdate(JSONPayload, lambda payload, responseStatus, token: self.shadowUpdateCompleteHandler(payload, responseStatus, token), 5)

    def connectDeviceShadow(self):
        host = "a30rsz8andmfjk.iot.ap-southeast-2.amazonaws.com"
        rootCAPath = "private/root-CA.crt"
        privateKeyPath = "private/DAAS_Door.private.key"
        certificatePath = "private/DAAS_Door.cert.pem"

        self._shadowClient = AWSIoTMQTTShadowClient(self._shadowName)
        self._shadowClient.configureEndpoint(host, 8883)
        self._shadowClient.configureCredentials(rootCAPath, privateKeyPath, certificatePath)

        # AWSIoTMQTTShadowClient configuration
        self._shadowClient.configureAutoReconnectBackoffTime(1, 32, 20)
        self._shadowClient.configureConnectDisconnectTimeout(10)  # 10 sec
        self._shadowClient.configureMQTTOperationTimeout(5)  # 5 sec
        self._shadowClient.connect()
        self._deviceShadow = self._shadowClient.createShadowHandlerWithName(self._shadowName, True)
        #self._deviceShadow.shadowDelete(lambda payload, responseStatus, token: self.shadowDeltaChangeHandler(payload, responseStatus, token), 5)
        self._deviceShadow.shadowRegisterDeltaCallback(lambda payload, responseStatus, token: self.shadowDeltaChangeHandler(payload, responseStatus, token))
        JSONPayload = '{"state":{"desired":{"property": 42}}}'
        self._deviceShadow.shadowUpdate(JSONPayload, lambda payload, responseStatus, token: self.shadowUpdateCompleteHandler(payload, responseStatus, token), 5)
        self._deviceShadow.shadowDelete(lambda payload, responseStatus, token: self.shadowDeleteCompleteHandler(payload, responseStatus, token), 5)

class DoorDevice(Device):
    def __init__(self):
        super(DoorDevice, self).__init__()
        self._shadowName = "XDimensionalDoor"

    def openDoor(self):
        print("updating shadow to flag door open")

    def closeDoor(self):
        print("updating shadow to flag door closed")

class DiscoDevice(Device):
    def __init__(self):
        super(DiscoDevice, self).__init__()
        self._shadowName = "DiscoMaster2000"

    def playbackStateChanged(self):
        print("our playback shadow state was changed")

class DoorThread(threading.Thread):
    def __init__(self, doorInstance):
        super(DoorThread, self).__init__()
        self._doorInstance = doorInstance

    def run(self):
        while True:
            time.sleep(1)
            print("tick")
            
class DiscoThread(threading.Thread):
    def __init__(self, discoInstance):
        super(DiscoThread, self).__init__()
        self._discoInstance = discoInstance

    def run(self):
        while True:
            time.sleep(1)
            print("tock")
            
# Configure logging
logger = logging.getLogger("AWSIoTPythonSDK.core")
logger.setLevel(logging.DEBUG)
streamHandler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
streamHandler.setFormatter(formatter)
logger.addHandler(streamHandler)

# now kick things off

door = DoorDevice()
door.connectDeviceShadow()

disco = DiscoDevice()
#disco.connectDeviceShadow()

doorTestThread = DoorThread(door)
discoTestThread = DiscoThread(disco)

#discoTestThread.start()
#doorTestThread.start()

while True:
    pass