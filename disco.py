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

# HACK
import boto3
import random
from datetime import datetime
from datetime import timedelta
import time

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
        self._macAddress = "-" # open('/sys/class/net/eth0/address').read()
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
        self._chanceOfRain = 0
        self._playlistDataMutex = Lock()
        self._playlistData = {}
        time_and_vol = self.time_check(self._latitude, self._longitude)
        self._localTimeString = time_and_vol["local_time_str"]
        self._volume = time_and_vol["volume"]
        self.checkWeather()
        self.checkPlaylist()
        self._s3 = boto3.resource('s3', region_name='ap-southeast-2')
        self._S3PollyBucket = self._s3.Bucket('daas-polly-files')
        self._S3Client = boto3.client('s3')
        self._pollyClient = boto3.client('polly', region_name = 'us-west-2')

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
            
    def applyShadowJSON(self, shadowJSON):
        unpackedJSON = json.loads(shadowJSON)
        unpackedJSON = unpackedJSON["state"]
        self._doorOpen = unpackedJSON["doorOpen"]

    def open(self):
        self._doorOpen = True
        self._doorOpenStartTime = time.time()
        time_and_vol = self.time_check(self._latitude, self._longitude)
        self._localTimeString = time_and_vol["local_time_str"]
        self._volume = time_and_vol["volume"]
        #self.updateShadow()        
        self.mockedLambda(json.loads(self.toShadowJSON()))

    def close(self):
        self._doorOpen = False
        self._openDuration = str(time.time() - self._doorOpenStartTime)
        #self.updateShadow()        
        self.mockedLambda(self.toShadowJSON())

    def checkWeather(self):
        Logger.log(logging.INFO, "Device's reported latitude: " + str(self._latitude))
        Logger.log(logging.INFO, "Device's reported longitude: " + str(self._longitude))
        Logger.log(logging.INFO, "Passing device geo-location to worldweatheronline to see if it is raining")
        apiurl = "http://api.worldweatheronline.com/premium/v1/weather.ashx?key=4d8f5ad3106b492ba1323348172206&q=%s,%s&num_of_days=1&format=json&localObsTime=yes" % (self._latitude, self._longitude)
        Logger.log(logging.INFO, "Making HTTP GET request to the following url: " + apiurl)
 
        chance_of_rain = 0
        ct = 0

        response = requests.get(apiurl)
        json_weather = "no weather"
        print(apiurl)

        try:
            json_weather = response.json()
            chance_of_rain = json_weather["data"]["weather"][0]["hourly"][0]["chanceofrain"]
            ct = json_weather["data"]["current_condition"][0]["temp_C"]
        except:
            Logger.log(logging.ERROR, "Full response from worldweatheronline: " + str(json_weather))

        Logger.log(logging.INFO, "chance_of_rain: " + str(chance_of_rain))  

        self._chanceOfRain = int(chance_of_rain)
        self._currentTemp = ct

    def which_song_to_play(self, songs):
        songcount = int(songs["Count"])
        print("count: ", songcount)
        songref = random.randint(0, songcount - 1)    
        print("songref: ", songref)
        song = songs["Items"][songref]
        print("songname: ",song)
        return song

    def time_check(self, latitude, longitude):
        print("Passing device geo-location to Google Maps TimeZone API to find local time offset")
        epochtime = time.time()
        print("epochtime: ", int(epochtime))
        apiurl = 'https://maps.googleapis.com/maps/api/timezone/json?location=%s,%s&timestamp=%d&key=AIzaSyBy-rsJ2uG-CEAWglzqdZEqMArAvrGEuFs' % (latitude,longitude,int(epochtime))
        print("Making HTTP GET request to the following url: ", apiurl)
        response = requests.get(apiurl)

        try:
            json_timezone = response.json()
            print("Successful call to Google Maps Time Zone API")
        except ValueError:
            json_timezone = response.text
            print("Unsuccessful call to Google Maps Time Zone API")

        print("Full response from Google Maps Timezone API: ", json_timezone)

        if json_timezone["status"] == "OK":
            # Calculate the local time at the provided geo-coordinates
            print("Received results from Google Maps")
            utc_offset = json_timezone["rawOffset"]+json_timezone["dstOffset"]
            print("utc_offset: ", utc_offset)
            utc_time_now = datetime.utcnow()
            print("utc_time_now: ", utc_time_now)
            local_time_now = utc_time_now + timedelta(seconds=utc_offset)
            print("local_time_now: ", local_time_now)
            print("hour: ", local_time_now.hour)
            if int(local_time_now.hour) > 19:
                print("Kids are in bed. Play disco at low volume")
                volume = 0.5
            else:
                print("It's daytime. Play disco at full volume")
                volume = 1.0

            print("string datetime: ", str(local_time_now))
            local_time_str=local_time_now.strftime('%I:%M%p')
        else:
            local_time_str = "unknown"    
            print("No results from Google Maps")

        return {'local_time_str': local_time_str, 'volume': volume}

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

    def createVoiceMessage(self, registeredOwner, current_temp, song_title, song_artist, time_str):
        print("---")
        print(registeredOwner)
        print(current_temp)
        print(song_title)
        print(song_artist)
        print(time_str)
        print("---")

        voiceMessage = "Welcome home " + registeredOwner + ", that was " + song_title + " by " + song_artist + ", the time is " + time_str + ", and the current temperature is " + str(current_temp) + " degrees." 
        print("Calling Polly with message: ",voiceMessage)
        response = self._pollyClient.synthesize_speech(Text=voiceMessage, VoiceId='Salli', OutputFormat='mp3')
        data_stream = response.get("AudioStream")
        filename = "%s.mp3" % registeredOwner
        print("Polly has created audio file: ",filename)
        self._S3PollyBucket.put_object(Key = filename, Body = data_stream.read())
        url = self._S3Client.generate_presigned_url(
            ClientMethod='get_object',
            Params={
                'Bucket': 'daas-polly-files',
                'Key': filename
            },
            ExpiresIn=3000
        )
        print("Pre-signed url with synthesized voice message: ", url)
        return url

    def mockedLambda(self, event):
        print("mockedLambda")
        '''
            TODO:
            Test comment in zip archive - delete this line
                - check whether the event JSON has open or closed state
                - check weather based on location in event data
                - log activity to elasticsearch for dashboard
        '''
        #pprint.pprint(event["state"]["desired"])
        doorstate = event["state"]["desired"]["doorstate"]

        if doorstate == "open":
            print("The door is open")
            # Using the MAC address of the device, lookup name of registered owner
            registeredOwner = event["state"]["desired"]["playlist"]["Owner"]
            print("Welcome home", registeredOwner)
            
            # Using the received latitude and longitude, determine current temperature and chance of rain
            chance_of_rain = event["state"]["desired"]["chance_of_rain"]
            current_temp = event["state"]["desired"]["current_temp"]
            print("Current temp: ", current_temp)
            chance_of_rain=50
            
            #If it's raining override song selection with "It's raining men", otherwise make song selection
            if chance_of_rain == 100:
                # FIX
                songitem = songListTable.get_item(Key={'title': 'its_raining_men'})
                song = songitem["Item"]
            else:
                song = self.which_song_to_play(event["state"]["desired"]["playlist"])    

            print("song: ", song)

            # Using the received latitude and longitude, determine local time
            #time_volume = time_check(latitude, longitude)
            time_at_disco = event["state"]["desired"]["local_time_str"]

            #volume=time_volume["volume"]
            volume = 1

            payload = {'state':{'desired':{'playbackStart': 'True', 'volume': 1.0, 'duration': 5, 'song': {'mark_in': '01', 'song_name': 'Im so excited', 'artist': 'Pointer Sisters', 'title': 'im_so_excited'}, 'url': 'http:\\blah_blah.com'}}}
            payload["state"]["desired"]["song"] = song
            
            voicemessageurl = self.createVoiceMessage(registeredOwner, current_temp, song['song_name'], song['artist'], time_at_disco)
            payload["state"]["desired"]["url"] = voicemessageurl
            payload["state"]["desired"]["volume"] = float(volume)
            json_message = json.dumps(payload)
            print("json_message: ", json_message)
            #response = client.update_thing_shadow(thingName = "DiscoMaster2000", payload = json_message)
            #print("response: ", response)
            print("return payload: ", payload)
            #To do. Log door opened status to elasticsearch
        else:
            print("The door is closed")
            #To do. Log door closed status to elasticsearch

        return "done"
        
class DiscoDevice(Device):
    def __init__(self):
        super(DiscoDevice, self).__init__()
        self._shadowName = "DAAS_Player"

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
        return stateDict
        
class LocalPollingThread(threading.Thread):
    def __init__(self, doorInstance):
        super(LocalPollingThread, self).__init__()
        self._doorInstance = doorInstance

    def run(self):
        try:
            while True:
                self._doorInstance.checkWeather()
                self._doorInstance.checkPlaylist()
                time.sleep(10)
        except KeyboardInterrupt:
            Logger.log(logging.INFO, "leaving thread")
            
#
## now kick things off
#
door = DoorDevice()
#door.connectDeviceShadow()
#
#disco = DiscoDevice()
#disco.connectDeviceShadow()

localPollingThread = LocalPollingThread(door)
localPollingThread.start()

try:
    while True:
        #Logger.log(logging.INFO, "---")
        #Logger.log(logging.INFO, "open door")
        door.open()
        #Logger.log(logging.INFO, "time: " + str(time.time()))
        #Logger.log(logging.INFO, "---")
        #playlist.getShadowState()
        #playlist.updateShadow()
        time.sleep(5)
        #pprint.pprint(json.loads(door.toShadowJSON()))
        #Logger.log(logging.INFO, "close door")
        #door.close()
        #time.sleep(5)

except KeyboardInterrupt:
        print('Interrupted')
        try:
            sys.exit(0)
        except SystemExit:
            os._exit(0)
