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
import socket

import pygame
#import RPi.GPIO as GPIO
#GPIO.setmode(GPIO.BCM)

DB1PIN=26
DB2PIN=13
DB3PIN=6

socket.setdefaulttimeout(3)

# HACK
import boto3
import random
from datetime import datetime
from datetime import timedelta
import time

# configure logging
Logger = logging.getLogger("AWSIoTPythonSDK.core")
Logger.setLevel(logging.INFO)
streamHandler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
streamHandler.setFormatter(formatter)
Logger.addHandler(streamHandler)

class Device(object):
    def __init__(self):
        self._shadowName = "<<UNNAMEDDEVICE>>"
        self._macAddress = "-" #open('/sys/class/net/eth0/address').read()
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
        self.applyShadowJSON(payload)

    def shadowGetCompleteHandler(self, payload, responseStatus, token):
        #print("shadow get complete: " + payload)
        self.applyShadowJSON(payload)
        
    def shadowUpdateCompleteHandler(self, payload, responseStatus, token):
        #print("shadow update completed: " + payload)
        updateDone = True
    
    def shadowDeleteCompleteHandler(self, payload, responseStatus, token):
        #print("shadow delete completed: " + payload)
        deleteDone = True

    def connectDeviceShadow(self):
        #host = "a30rsz8andmfjk.iot.ap-southeast-2.amazonaws.com"
        #rootCAPath = "private/root-CA.crt"

        #host = "192.168.3.214"
        #host = "127.0.0.1"
        #host = "HappyHomeGroup_Core"
        #rootCAPath = "private/core/dev.crt"
        
        print(self._shadowName)
    
        self._shadowClient = AWSIoTMQTTShadowClient(self._shadowName)
        self._shadowClient.configureEndpoint(self._host, 8883)
        self._shadowClient.configureCredentials(self._rootCAPath, self._privateKeyPath, self._certificatePath)

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
        
class LocalPollingThread(threading.Thread):
    def __init__(self, doorInstance):
        super(LocalPollingThread, self).__init__()
        self._doorInstance = doorInstance

    def run(self):
        try:
            while True:
                if self._doorInstance.checkPlaylist():
                    self._doorInstance.checkWeather()

                time.sleep(360)
        except KeyboardInterrupt:
            Logger.log(logging.INFO, "leaving thread")

class VOXDevice(Device):
    def __init__(self):
        super(VOXDevice, self).__init__()
        self._shadowName = "DAAS_VOX"
        self._stateData = {}

    def connectDeviceShadow(self):
        self._privateKeyPath = "private/DAAS_VOX_23aa8f6c21-private.pem.key"
        self._certificatePath = "private/DAAS_VOX_23aa8f6c21-certificate.pem.crt"
        self._host = "a30rsz8andmfjk.iot.us-west-2.amazonaws.com"
        self._rootCAPath = "private/root-CA.crt"
        super(VOXDevice, self).connectDeviceShadow()
        Logger.log(logging.INFO, "vox alive")
        self.getShadowState()

    def applyShadowJSON(self, shadowJSON):
        try:
            unpackedJSON = json.loads(shadowJSON)["state"]
            pprint.pprint(unpackedJSON)
        except:
            Logger.log(logging.ERROR, "vox shadow get error")        

# Class DoorDevice extends class device by adding functions specific to the DAAS connected door
class DoorDevice(Device):
    def __init__(self, pin):
        super(DoorDevice, self).__init__()
        self._shadowName = "DAAS_FrontDoor"
        self._doorOpen = False
        self._openDuration = 0
        self._chanceOfRain = 0
        self._playlistDataMutex = Lock()
        self._playlistData = {}
        time_and_vol = self.time_check(self._latitude, self._longitude)
        self._localTimeString = time_and_vol["local_time_str"]
        self._volume = time_and_vol["volume"]
        self.checkWeather()
        self.checkPlaylist()
        #GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        self._localPollingThread = LocalPollingThread(self)
        self._localPollingThread.start()

        key_id = "-"
        key_secret = "-"

        self._s3 = boto3.resource('s3', region_name='ap-southeast-2', aws_access_key_id = key_id, aws_secret_access_key = key_secret)
        self._S3DoorStatusBucket = self._s3.Bucket('daas-door-status')

    def connectDeviceShadow(self):
        self._privateKeyPath = "private/door/806bf01189-private.pem.key"
        self._certificatePath = "private/door/806bf01189-certificate.pem.crt"
        self._host = "HappyHomeGroup_Core"
        self._rootCAPath = "private/core/dev.crt"

        super(DoorDevice, self).connectDeviceShadow()

        if self.checkPlaylist():
            time_and_vol = self.time_check(self._latitude, self._longitude)
            self._localTimeString = time_and_vol["local_time_str"]
            self._volume = time_and_vol["volume"]
            self.checkWeather()
        else:
            self._localTimeString = time.strftime("%I:%M%p")
            self._volume = 0.5
            self.getShadowState()
        
    def desiredStateDictionary(self):
        desiredState = super(DoorDevice, self).desiredStateDictionary()
        if self._doorOpen:
            desiredState["doorstate"] = "open"
            desiredState["timeopen"] = "0"
        else:
            desiredState["doorstate"] = "closed"
            desiredState["timeopen"] = self._openDuration

        # protect reads of this blob of data - the background playlist update
        # thread may well be writing to it
        self._playlistDataMutex.acquire()
        desiredState["playlist"] = self._playlistData
        self._playlistDataMutex.release()

        desiredState["chance_of_rain"] = self._chanceOfRain
        desiredState["current_temp"] = self._currentTemp
        desiredState["local_time_str"] = self._localTimeString
        desiredState["volume"] = self._volume

        return desiredState

    def updateShadow(self):
        super(DoorDevice, self).updateShadow()
        # update the door-state.json file in the given S3 bucket
        # so that our polling page can show it to a human

        stateString = ""
        if self._doorOpen:
            stateString = "open"
        else:
            stateString = "closed"

        webJSON = {"doorState": stateString,
                   "registeredOwner": self._playlistData["Owner"]}
        pprint.pprint(webJSON)

        try:
            self._S3DoorStatusBucket.put_object(Key = "door-status.json", Body = json.dumps(webJSON))
        except:
            print("s3 json status put error")

    def setPlaylist(self, playlist):
        # protect reads of this blob of data - the background playlist update
        # thread may well be writing to it
        self._playlistDataMutex.acquire()
        self._playlistData = playlist
        self._playlistDataMutex.release()
        
    def applyShadowJSON(self, shadowJSON):
        try:
            unpackedJSON = json.loads(shadowJSON)["state"]["desired"]            
            self.setPlaylist(unpackedJSON["playlist"])
            self._doorOpen = unpackedJSON["doorstate"]
            self._chanceOfRain = unpackedJSON["chance_of_rain"]
            self._currentTemp = unpackedJSON["current_temp"]
            self._localTimeString = unpackedJSON["local_time_str"]
            self._volume = unpackedJSON["volume"]
        except:
            Logger.log(logging.ERROR, "door shadow get error")

    def open(self):
        self._doorOpen = True
        self._doorOpenStartTime = time.time()
        time_and_vol = self.time_check(self._latitude, self._longitude)

        if time_and_vol["status"] == "OK":
            self._localTimeString = time_and_vol["local_time_str"]
            self._volume = time_and_vol["volume"]
        else:
            self._localTimeString = time.strftime("%I:%M%p")
            
        self.updateShadow()        
        print("open sesame")
        
    def close(self):
        self._doorOpen = False
        self._openDuration = str(time.time() - self._doorOpenStartTime)
        self.updateShadow()        

    def checkWeather(self):
        Logger.log(logging.INFO, "Device's reported latitude: " + str(self._latitude))
        Logger.log(logging.INFO, "Device's reported longitude: " + str(self._longitude))
        Logger.log(logging.INFO, "Passing device geo-location to worldweatheronline to see if it is raining")
        apiurl = "http://api.worldweatheronline.com/premium/v1/weather.ashx?key=4d8f5ad3106b492ba1323348172206&q=%s,%s&num_of_days=1&format=json&localObsTime=yes" % (self._latitude, self._longitude)
        Logger.log(logging.INFO, "Making HTTP GET request to the following url: " + apiurl)
 
        chance_of_rain = 0
        ct = 0

        json_weather = "no weather"
        print(apiurl)

        try:
            response = requests.get(apiurl)
            json_weather = response.json()
            chance_of_rain = json_weather["data"]["weather"][0]["hourly"][0]["chanceofrain"]
            ct = json_weather["data"]["current_condition"][0]["temp_C"]
        except:
            Logger.log(logging.ERROR, "Full response from worldweatheronline: " + str(json_weather))
            
        Logger.log(logging.INFO, "chance_of_rain: " + str(chance_of_rain))  

        self._chanceOfRain = int(chance_of_rain)
        self._currentTemp = ct
    
    def time_check(self, latitude, longitude):
        Logger.log(logging.INFO, "Passing device geo-location to Google Maps TimeZone API to find local time offset")
        epochtime = time.time()

        apiurl = 'https://maps.googleapis.com/maps/api/timezone/json?location=%s,%s&timestamp=%d&key=AIzaSyBy-rsJ2uG-CEAWglzqdZEqMArAvrGEuFs' % (latitude,longitude,int(epochtime))
        Logger.log(logging.INFO, "Making HTTP GET request to the following url: " + str(apiurl))

        try:
            response = requests.get(apiurl)
            json_timezone = response.json()
            Logger.log(logging.INFO, "Successful call to Google Maps Time Zone API")
        except:
            json_timezone = {"status": "error"}
            Logger.log(logging.ERROR, "Unsuccessful call to Google Maps Time Zone API")

        print("Full response from Google Maps Timezone API: ", json_timezone)

        volume = 0.5
        status = "OK"
        
        if json_timezone["status"] == "OK":
            # Calculate the local time at the provided geo-coordinates
            #print("Received results from Google Maps")
            utc_offset = json_timezone["rawOffset"]+json_timezone["dstOffset"]
            #print("utc_offset: ", utc_offset)
            utc_time_now = datetime.utcnow()
            #print("utc_time_now: ", utc_time_now)
            local_time_now = utc_time_now + timedelta(seconds=utc_offset)
            #print("local_time_now: ", local_time_now)
            #print("hour: ", local_time_now.hour)
            
            if int(local_time_now.hour) > 19:
                print("Kids are in bed. Play disco at low volume")
                volume = 0.5
            else:
                print("It's daytime. Play disco at full volume")
                volume = 1.0

            print("string datetime: ", str(local_time_now))
            local_time_str=local_time_now.strftime('%I:%M%p')
        else:
            local_time_str = "00:00:00"
            status = "error"
            print("No results from Google Maps")

        return {"local_time_str": local_time_str, "volume": volume, "status": status}

    '''
        calls API gateway endpoint with access key to extract json dump from dynamodb table which
        contains the playlist and ownername

        - thread safe
    '''    
    def checkPlaylist(self):
        result = True
        try:
            url = "https://yoq0oxlvog.execute-api.ap-southeast-2.amazonaws.com/base?macaddr=%s" % (self._macAddress)
            request = urllib.request.Request(url, headers = {"x-api-key": "ULi868dax46EqcuBr1Y6X7llnNOyZS8i48yKf1E9"})
            with urllib.request.urlopen(request) as response:
                data = response.readall().decode("utf-8")
                playlist = json.loads(data)
                self.setPlaylist(playlist)
                Logger.log(logging.INFO, "got playlist")
        except Exception as e:
            Logger.log(logging.INFO, "playlist fetch error: " + str(e))
            self._playlistData = {"Owner": "resident", "Count": 1, "Items": [{"song_name": "dont leave me this way", "artist": "unknown"}]}
            Logger.log(logging.ERROR, "playlist check failed")
            result = False
        return result

class DiscoBall():
    def __init__(self, pin):
        self._pin = pin
        print("__init__ of DiscoBall")
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.HIGH)

    def start(self):
        print("Starting to spin disco ball on pin " + str(self._pin))
        GPIO.output(self._pin, GPIO.LOW)
       
    def stop(self):
        print("Stopping the disco ball")
        GPIO.output(self._pin, GPIO.HIGH)
        
class DiscoDevice(Device):
    def __init__(self):
        super(DiscoDevice, self).__init__()

        key_id = "-"
        key_secret = "-"
        
        self._shadowName = "DAAS_Player"
        self._s3 = boto3.resource('s3', region_name='ap-southeast-2', aws_access_key_id = key_id, aws_secret_access_key = key_secret)
        self._S3PollyBucket = self._s3.Bucket('daas-polly-files')
        self._S3Client = boto3.client('s3', aws_access_key_id = key_id, aws_secret_access_key = key_secret)
        self._pollyClient = boto3.client('polly', region_name = 'us-west-2', aws_access_key_id = key_id, aws_secret_access_key = key_secret)

    def connectDeviceShadow(self):
        self._privateKeyPath = "private/player/14a52be2ca-private.pem.key"
        self._certificatePath = "private/player/14a52be2ca-certificate.pem.crt"
        super(DiscoDevice, self).connectDeviceShadow()

    def shadowDeltaChangeHandler(self, payload, responseStatus, token):
        self.applyShadowJSON(payload)

    def createPollyMessageURL(self, messageText, registeredOwner):
        url = ""
        try:
            print("Calling Polly with message: ", messageText)
            response = self._pollyClient.synthesize_speech(Text = messageText, VoiceId = 'Salli', OutputFormat = 'mp3')
            data_stream = response.get("AudioStream")
            filename = "%s.mp3" % registeredOwner
            print("Polly has created audio file: ", filename)
            self._S3PollyBucket.put_object(Key = filename, Body = data_stream.read())
            url = self._S3Client.generate_presigned_url(
                ClientMethod='get_object',
                Params={
                    'Bucket': 'daas-polly-files',
                    'Key': filename
                },
                ExpiresIn = 3000
            )
        except:
            url = ""
        return url

    def playDisco(self, songname, voiceMessage, registeredOwner, mark_in, volume, duration):
        print("shake your booty on the dance floor!")
        discoball1 = DiscoBall(DB1PIN)
        discoball2 = DiscoBall(DB2PIN)
        discoball3 = DiscoBall(DB3PIN)
        discoball1.start()
        discoball2.start()
        discoball3.start()

        # Play the song file
        print("now playing " + songname)
        pygame.mixer.init()
        songpath="songs/"+songname+".mp3"
        print("songpath" + songpath)
        pygame.mixer.music.load(songpath)
        pygame.mixer.music.set_volume(volume)
        discostarttime=time.time()
        print("discostarttime: ",discostarttime)
        discoendtime=discostarttime+duration
        print("discoendtime: ",discoendtime)

        # playback through pygame sometimes fails - so give it up to three attempts
        
        playAttempts = 0
        while playAttempts < 3:
            try:
                pygame.mixer.music.play(start=float(mark_in))
                playAttempts = 3
            except:
                playAttempts = playAttempts + 1

        # Download the Welcome Home message while song plays
        messageURL = self.createPollyMessageURL(voiceMessage, registeredOwner)

        if len(messageURL) > 0:
            urllib.request.urlretrieve(messageURL, "voicemsg.mp3")

            while time.time() < discoendtime:
                time.sleep(1)

        time.sleep(5)

        fadeoutAttempts = 0
        while fadeoutAttempts < 3:
            try:
                pygame.mixer.music.fadeout(3000)
                fadeoutAttempts = 3
                time.sleep(3)
            except:
                print("mixer error")
                fadeoutAttempts = fadeoutAttempts + 1

        try:
            discoball1.stop()
            discoball2.stop()
            discoball3.stop()
        except:
            print("disco hw stop error")

        if len(messageURL) > 0:
            try:
                pygame.mixer.music.load("voicemsg.mp3")
                pygame.mixer.music.play()
                time.sleep(10)
            except:
                print("message play error")
        
        pygame.mixer.quit()

    def applyShadowJSON(self, shadowJSON):
        #print("DiscoDevice shadow update: " + shadowJSON)
        #print(time.time())
        print("---")
        
        unpackedJSON = json.loads(shadowJSON)
        unpackedJSON = unpackedJSON["state"]

        if unpackedJSON["playbackStart"]:
            self.playDisco(unpackedJSON["song"]["title"],
                           unpackedJSON["greeting_text"],
                           unpackedJSON["registeredOwner"],
                           unpackedJSON["song"]["mark_in"],
                           unpackedJSON["volume"],
                           unpackedJSON["duration"])

    # write our derived class properties to our serialised state dictionary
    def desiredStateDictionary(self):
        stateDict = super(DiscoDevice, self).desiredStateDictionary()
        return stateDict
                    
#
## now kick things off
#

voxControlDevice = VOXDevice()
voxControlDevice.connectDeviceShadow()

#door = DoorDevice(5)
#door.checkWeather()
#door.connectDeviceShadow()
#
#disco = DiscoDevice()
#disco.playDisco("songy song song", "oh hi!", "smithy", 0, 10, 10)
#disco.connectDeviceShadow()

try:
    while True:
        Logger.log(logging.INFO, "---")
        #Logger.log(logging.INFO, "open door")
        #door.open()
        #Logger.log(logging.INFO, "time: " + str(time.time()))
        #Logger.log(logging.INFO, "---")
        #playlist.getShadowState()
        #playlist.updateShadow()
        #time.sleep(5)
        #pprint.pprint(json.loads(door.toShadowJSON()))
        #Logger.log(logging.INFO, "close door")
        #door.close()
        time.sleep(5)

except KeyboardInterrupt:
        print('Interrupted')
        try:
            sys.exit(0)
        except SystemExit:
            os._exit(0)

