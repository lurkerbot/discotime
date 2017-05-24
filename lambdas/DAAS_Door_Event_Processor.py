import boto3
import json

client = boto3.client('iot-data', region_name = 'ap-southeast-2')

def lambda_handler(event, context):
    json_message = json.dumps({"state":{"desired":{"playbackStart": True}}})
    response = client.update_thing_shadow(thingName = "DiscoMaster2000", payload = json_message)
    print response
    return "done"
