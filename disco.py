import sys

# drag in the SDK from aws-iot-device-sdk-python
sys.path.append("aws-iot-device-sdk-python")
from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTShadowClient

from threading import Thread, Lock
import json
import urllib.request
import os
import threading
import logging
import time
import json
import getopt
import requests
import pprint

# configure logging

Logger = logging.getLogger("AWSIoTPythonSDK.core")
Logger.setLevel(logging.ERROR)
streamHandler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
streamHandler.setFormatter(formatter)
Logger.addHandler(streamHandler)

class Device(object):
    def __init__(self):
        self._shadowName = "<<UNNAMEDDEVICE>>"
        self._macAddress = open('/sys/class/net/eth0/address').read()
        self._doorOpenStartTime = 0
        try:
            request = requests.get("http://freegeoip.net/json")
            requestJSON = json.loads(request.text)
            self._latitude = requestJSON["latitude"]
            self._longitude = requestJSON["longitude"]
        except:
            self._latitude = 0
            self._longitude = 0
        
    '''
        push current class instance state as JSON to IoT shadow device
    '''
    def updateShadow(self):
        self._deviceShadow.shadowUpdate(self.toShadowJSON(),
                                        lambda payload, responseStatus, token: self.shadowUpdateCompleteHandler(payload, responseStatus, token),
                                        5)

    ''' 
        subclasses implement this method to convert the current
        instance state to JSON for use in an IoT device shadow update
        call
    '''
    def toShadowJSON(self):
        desiredState = self.desiredStateDictionary()
        return json.dumps({"state": {"desired": desiredState}})

    '''
        sublcasses implement this method to apply IoT shadow update
        delta JSON to the current instance state
    '''
    def applyShadowJSON(self, shadowJSON):
        assert(False) # must implement

    def shadowDeltaChangeHandler(self, payload, responseStatus, token):
        print("our shadow was updated: " + payload)
        self.applyShadowJSON(payload)

    def shadowGetCompleteHandler(self, payload, responseStatus, token):
        print("shadow get complete: " + payload)
        self.applyShadowJSON(payload)
        
    def shadowUpdateCompleteHandler(self, payload, responseStatus, token):
        print("shadow update completed: " + payload)
        updateDone = True
    
    def shadowDeleteCompleteHandler(self, payload, responseStatus, token):
        print("shadow delete completed: " + payload)
        deleteDone = True

    def connectDeviceShadow(self):
        #host = "a30rsz8andmfjk.iot.ap-southeast-2.amazonaws.com"
        #rootCAPath = "private/root-CA.crt"

        #host = "192.168.3.214"
        host = "127.0.0.1"
        rootCAPath = "private/core/dev.crt"
        
        print(self._shadowName)
    
        self._shadowClient = AWSIoTMQTTShadowClient(self._shadowName)
        self._shadowClient.configureEndpoint(host, 8883)
        self._shadowClient.configureCredentials(rootCAPath, self._privateKeyPath, self._certificatePath)

        # AWSIoTMQTTShadowClient configuration
        self._shadowClient.configureAutoReconnectBackoffTime(5, 250, 20)
        self._shadowClient.configureConnectDisconnectTimeout(10)  # 10 sec
        self._shadowClient.configureMQTTOperationTimeout(25)  # 5 sec
        self._shadowClient.connect()

        self._deviceShadow = self._shadowClient.createShadowHandlerWithName(self._shadowName, True)
        self._deviceShadow.shadowRegisterDeltaCallback(lambda payload, responseStatus, token: self.shadowDeltaChangeHandler(payload, responseStatus, token))

        print("device connected")
        # restore our state to that of the shadow device on our IoT service
        #self.updateShadow()

    def sendShadowUpdate(self, payload):
        self._deviceShadow.shadowUpdate(payload, lambda payload, responseStatus, token: self.shadowUpdateCompleteHandler(payload, responseStatus, token), 5)

    def desiredStateDictionary(self):
        desiredState = {}
        desiredState["macaddress"] = self._macAddress.rstrip("\n")
        desiredState["latitude"] = self._latitude
        desiredState["longitude"] = self._longitude
        return desiredState

    def getShadowState(self):
        self._deviceShadow.shadowGet(lambda payload, responseStatus, token: self.shadowGetCompleteHandler(payload, responseStatus, token), 2)
        
# Class DoorDevice extends class device by adding functions specific to the DAAS connected door
class DoorDevice(Device):
    def __init__(self):
        super(DoorDevice, self).__init__()
        self._shadowName = "DAAS_FrontDoor"
        self._doorOpen = False
        self._openDuration = 0

    def connectDeviceShadow(self):
        self._privateKeyPath = "private/door/806bf01189-private.pem.key"
        self._certificatePath = "private/door/806bf01189-certificate.pem.crt"
        super(DoorDevice, self).connectDeviceShadow()
        
    def desiredStateDictionary(self):
        desiredState = super(DoorDevice, self).desiredStateDictionary()
        if self._doorOpen:
            desiredState["doorstate"] = "open"
            desiredState["timeopen"] = "0"
        else:
            desiredState["doorstate"] = "closed"
            desiredState["timeopen"] = self._openDuration
        return desiredState
            
    def toShadowJSON(self):
        desiredState = self.desiredStateDictionary()
        return json.dumps({"state": {"desired": desiredState}})

    def applyShadowJSON(self, shadowJSON):
        unpackedJSON = json.loads(shadowJSON)
        unpackedJSON = unpackedJSON["state"]
        self._doorOpen = unpackedJSON["doorOpen"]

    def open(self):
        self._doorOpen = True
        self._doorOpenStartTime = time.time()
        self.updateShadow()        

    def close(self):
        self._doorOpen = False
        self._openDuration = str(time.time() - self._doorOpenStartTime)
        self.updateShadow()        
        
class DiscoDevice(Device):
    def __init__(self):
        super(DiscoDevice, self).__init__()
        self._chanceOfRain = 0
        self._shadowName = "DAAS_Player"
        self._playlistDataMutex = Lock()
        self._playlistData = {}
        self.checkWeather()
        self.checkPlaylist()

    def connectDeviceShadow(self):
        self._privateKeyPath = "private/player/14a52be2ca-private.pem.key"
        self._certificatePath = "private/player/14a52be2ca-certificate.pem.crt"
        super(DiscoDevice, self).connectDeviceShadow()

    def shadowDeltaChangeHandler(self, payload, responseStatus, token):
        self.applyShadowJSON(payload)

    def playDisco(self):
        print("shake your booty on the dance floor!")

    def applyShadowJSON(self, shadowJSON):
        print("DiscoDevice shadow update: " + shadowJSON)
        print(time.time())
        print("---")
        unpackedJSON = json.loads(shadowJSON)
        unpackedJSON = unpackedJSON["state"]
        if unpackedJSON["playbackStart"]:
            self.playDisco()

    # write our derived class properties to our serialised state dictionary
    def desiredStateDictionary(self):
        stateDict = super(DiscoDevice, self).desiredStateDictionary()

        # protect reads of this blob of data - the background playlist update
        # thread may well be writing to it
        self._playlistDataMutex.acquire()
        stateDict["playlist"] = self._playlistData
        self._playlistDataMutex.release()

        stateDict["chance_of_rain"] = self._chanceOfRain
        return stateDict

    def checkWeather(self):
        Logger.log(logging.INFO, "Device's reported latitude: " + str(self._latitude))
        Logger.log(logging.INFO, "Device's reported longitude: " + str(self._longitude))
        Logger.log(logging.INFO, "Passing device geo-location to worldweatheronline to see if it is raining")
        apiurl = "http://api.worldweatheronline.com/premium/v1/weather.ashx?key=d4dab5e2738542f884000750172904&q=%s,%s&num_of_days=1&format=json&localObsTime=yes" % (self._latitude, self._longitude)
        Logger.log(logging.INFO, "Making HTTP GET request to the following url: " + apiurl)
 
        chance_of_rain = 0
        response = requests.get(apiurl)
        
        try:
            json_weather = response.json()
            chance_of_rain = json_weather["data"]["weather"][0]["hourly"][0]["chanceofrain"]
        except ValueError as e:
            Logger.log(logging.ERROR, "Full response from worldweatheronline: ", e)

        Logger.log(logging.INFO, "chance_of_rain: " + str(chance_of_rain))            
        self._chanceOfRain = int(chance_of_rain)

    '''
        calls API gateway endpoint with access key to extract json dump from dynamodb table which
        contains the playlist and ownername

        - thread safe
    '''    
    def checkPlaylist(self):
        locked = False
        print("checking for latest disco playlist")

        try:
            url = "https://yoq0oxlvog.execute-api.ap-southeast-2.amazonaws.com/base?macaddr=%s" % (self._macAddress)
            request = urllib.request.Request(url, headers = {"x-api-key": "ULi868dax46EqcuBr1Y6X7llnNOyZS8i48yKf1E9"})
            with urllib.request.urlopen(request) as response:
                data = response.read()
                self._playlistDataMutex.acquire()
                locked = True
                self._playlistData = json.loads(data)
                Logger.log(logging.INFO, "got playlist")
        except Exception as e:
            Logger.log(logging.INFO, "playlist fetch error: " + str(e))
        finally:
            if locked:
                self._playlistDataMutex.release()

class PlaylistDevice(Device):
    def __init__(self):
        super(PlaylistDevice, self).__init__()
        self._chanceOfRain = 0
        # test
        self._shadowName = "DAAS_Playlist"

    def connectDeviceShadow(self):
        self._privateKeyPath = "private/playlist/1e055a15f2-private.pem.key"
        self._certificatePath = "private/playlist/1e055a15f2-certificate.pem.crt"
        super(PlaylistDevice, self).connectDeviceShadow()

    def shadowUpdateCompleteHandler(self, payload, responseStatus, token):
        print("snarf shadow update completed: " + payload)
        updateDone = True

    def applyShadowJSON(self, shadowJSON):
        print("DiscoDevice shadow update: " + shadowJSON)
        print(time.time())
        print("---")
        #unpackedJSON = json.loads(shadowJSON)
        #unpackedJSON = unpackedJSON["state"]
        #if unpackedJSON["playbackStart"]:
        #    self.playDisco()
        
class DiscoBackgroundThread(threading.Thread):
    def __init__(self, discoInstance):
        super(DiscoBackgroundThread, self).__init__()
        self._discoInstance = discoInstance

    def run(self):
        try:
            while True:
                self._discoInstance.checkWeather()
                self._discoInstance.checkPlaylist()
                time.sleep(10)
        except KeyboardInterrupt:
            Logger.log(logging.INFO, "leaving thread")
            
#
## now kick things off
#
#door = DoorDevice()
#door.connectDeviceShadow()
#
disco = DiscoDevice()
#disco.connectDeviceShadow()

#playlist = PlaylistDevice()
#playlist.connectDeviceShadow()

discoTestThread = DiscoBackgroundThread(disco)
discoTestThread.start()

try:
    while True:
        #Logger.log(logging.INFO, "---")
        #Logger.log(logging.INFO, "open door")
        #door.open()
        #Logger.log(logging.INFO, "time: " + str(time.time()))
        #Logger.log(logging.INFO, "---")
        #playlist.getShadowState()
        #playlist.updateShadow()
        time.sleep(3)
        pprint.pprint(json.loads(disco.toShadowJSON()))
        #Logger.log(logging.INFO, "close door")
        #door.close()
        #time.sleep(5)

except KeyboardInterrupt:
        print('Interrupted')
        try:
            sys.exit(0)
        except SystemExit:
            os._exit(0)
