"""
http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.
"""

from botocore.vendored import requests
import boto3
import json
import string
import random
import time
import resource_tools


def event_handler(event, context):
    """
    Lambda entry point. Print the event first.
    """
    print("Event Input: %s" % json.dumps(event))
    try:
        medialive = boto3.client('medialive')
        if event["RequestType"] == "Create":
            result = create_channel(medialive, event, context)
        elif event["RequestType"] == "Update":
            result = update_channel(medialive, event, context)
        elif event["RequestType"] == "Delete":
            result = delete_channel(medialive, event, context)
    except Exception as exp:
        print("Exception: %s" % exp)
        result = {
            'Status': 'FAILED',
            'Data': {"Exception": str(exp)},
            'ResourceId': None
        }
    resource_tools.send(event, context, result['Status'],
                        result['Data'], result['ResourceId'])
    return


def create_channel(medialive, event, context, auto_id=True):
    """
    Create a MediaLive channel
    Return the channel URL, username and password generated by MediaLive
    """

    if auto_id:
        channel_id = "%s-%s" % (resource_tools.stack_name(event), event["LogicalResourceId"])
    else:
        channel_id = event["PhysicalResourceId"]

    try:

        destinations = {
            'p_url': event["ResourceProperties"]["PackagerPrimaryChannelUrl"], 'p_u': event["ResourceProperties"]["PackagerPrimaryChannelUsername"], 'p_p': event["ResourceProperties"]["PackagerPrimaryChannelUsername"],
            'b_url': event["ResourceProperties"]["PackagerSecondaryChannelUrl"], 'b_u': event["ResourceProperties"]["PackagerSecondaryChannelUsername"], 'b_p': event["ResourceProperties"]["PackagerSecondaryChannelUsername"]
        }

        channel_id = create_live_channel(event["ResourceProperties"]["MediaLiveInputId"], channel_id, [
                                         720, 540, 360], destinations, event["ResourceProperties"]["MediaLiveAccessRoleArn"], medialive)

        result = {
            'Status': 'SUCCESS',
            'Data': {},
            'ResourceId': channel_id
        }

        # wait untl the channel is idle, otherwise the lambda will time out
        resource_tools.wait_for_channel_states(medialive, channel_id, ['IDLE'])
        medialive.start_channel(ChannelId=channel_id)

    except Exception as ex:
        print(ex)
        result = {
            'Status': 'FAILED',
            'Data': {"Exception": str(ex)},
            'ResourceId': channel_id
        }

    return result


def update_channel(medialive, event, context):
    """
    Update a MediaLive channel
    Return the channel URL, username and password generated by MediaLive
    """

    channel_id = event["PhysicalResourceId"]

    try:
        result = delete_channel(medialive, event, context)
        if result['Status'] == 'SUCCESS':
            result = create_channel(medialive, event, context, False)

    except Exception as ex:
        print(ex)
        result = {
            'Status': 'FAILED',
            'Data': {"Exception": str(ex)},
            'ResourceId': channel_id
        }

    return result


def delete_channel(medialive, event, context):
    """
    Delete a MediaLive channel
    Return success/failure
    """

    channel_id = event["PhysicalResourceId"]

    try:
        # stop the channel
        medialive.stop_channel(ChannelId=channel_id)
        # wait untl the channel is idle, otherwise the lambda will time out
        resource_tools.wait_for_channel_states(medialive, channel_id, ['IDLE'])

    except Exception as ex:
        # report it and continue
        print(ex)

    try:
        response = medialive.delete_channel(ChannelId=channel_id)
        result = {
            'Status': 'SUCCESS',
            'Data': {},
            'ResourceId': channel_id
        }

    except Exception as ex:
        print(ex)
        result = {
            'Status': 'FAILED',
            'Data': {"Exception": str(ex)},
            'ResourceId': channel_id
        }

    return result


def get_video_description(w, h, b, n, qvbr):    
    video_description = {
        'Height': int(h),
        'Width': int(w),
        'CodecSettings': {
            'H264Settings': {
                'AdaptiveQuantization': 'HIGH',
                'Bitrate': int(b),
                'BufSize': int(b * 1.5),
                'BufFillPct': 90,
                'EntropyEncoding': 'CABAC',
                'FlickerAq': 'ENABLED',
                'FramerateControl': 'INITIALIZE_FROM_SOURCE',
                'GopBReference': 'DISABLED',
                'GopClosedCadence': 1,
                'GopNumBFrames': 2,
                'GopSize': 2,
                'GopSizeUnits': 'SECONDS',
                'Level': 'H264_LEVEL_AUTO',
                'LookAheadRateControl': 'HIGH',
                'MaxBitrate': b,
                'MinIInterval': 0,
                'NumRefFrames': 1,
                'ParControl': 'INITIALIZE_FROM_SOURCE',
                'Profile': 'MAIN',
                'RateControlMode': 'QVBR',
                'QvbrQualityLevel': qvbr,
                'Syntax': 'DEFAULT',
                'SceneChangeDetect': 'ENABLED',
                'Slices': 1,
                'SpatialAq': 'ENABLED',
                'TemporalAq': 'ENABLED',
            }
        },
        'Name': str(n),
        'RespondToAfd': 'NONE',
        'Sharpness': 50,
        'ScalingBehavior': 'DEFAULT',
    }
    return video_description


def get_output(n):
    output = {
        'OutputSettings': {
            'HlsOutputSettings': {
                'NameModifier': '_' + str(n),
                'HlsSettings': {
                    'StandardHlsSettings': {
                        'M3u8Settings': {
                            'AudioPids': '492-498',
                            'EcmPid': '8182',
                            'PatInterval': 0,
                            'PcrControl': 'PCR_EVERY_PES_PACKET',
                            'PcrPid': '481',
                            'PmtInterval': 0,
                            'PmtPid': '480',
                            'ProgramNum': 1,
                            'Scte35Pid': '500',
                            'Scte35Behavior': 'PASSTHROUGH',
                            'TimedMetadataBehavior': 'NO_PASSTHROUGH',
                            'VideoPid': '481'
                        },
                        'AudioRenditionSets': 'program_audio'
                    }
                }
            }
        },
        'OutputName': str(n),
        'VideoDescriptionName': str(n),
        'AudioDescriptionNames': ['audio1'],
        'CaptionDescriptionNames': []
    }
    return output


def get_encoding_settings(layer, bitrateperc=1.0, framerate=1.0):
    # recommended bitrates for workshop samples
    c = {
        '1080': {'width': 1920,  'height': 1080, 'bitrate': 4000000, 'qvbr': 8},
        '720': {'width': 1280,  'height': 720,  'bitrate': 3800000, 'qvbr': 8},
        '540': {'width': 960,   'height': 540,  'bitrate': 2300000, 'qvbr': 7},
        '504': {'width': 896,   'height': 504,  'bitrate': 2100000, 'qvbr': 7},
        '480': {'width': 854,   'height': 480,  'bitrate': 2000000, 'qvbr': 7},
        '468': {'width': 832,   'height': 468,  'bitrate': 1800000, 'qvbr': 7},
        '432': {'width': 768,   'height': 432,  'bitrate': 1600000, 'qvbr': 7},
        '396': {'width': 704,   'height': 396,  'bitrate': 1300000, 'qvbr': 6},
        '360': {'width': 640,   'height': 360,  'bitrate': 1200000, 'qvbr': 6},
        '324': {'width': 576,   'height': 324,  'bitrate': 1100000, 'qvbr': 6},
        '288': {'width': 512,   'height': 288,  'bitrate':  860000, 'qvbr': 5},
        '270': {'width': 480,   'height': 270,  'bitrate':  750000, 'qvbr': 5},
        '252': {'width': 448,   'height': 252,  'bitrate':  680000, 'qvbr': 4},
        '234': {'width': 416,   'height': 234,  'bitrate':  640000, 'qvbr': 4},
        '216': {'width': 384,   'height': 216,  'bitrate':  550000, 'qvbr': 3},
        '144': {'width': 256,   'height': 144,  'bitrate':  264000, 'qvbr': 3}
    }
    this_layer = c[layer]
    this_layer['bitrate'] = int(
        float(float(this_layer['bitrate']) * bitrateperc) * framerate)
    return this_layer


def create_live_channel(input_id, channel_name, layers, destinations, arn, medialive):
    video_descriptions = []
    outputs = []
    # go through each layer
    for l in layers:
        if isinstance(l, int):
            c = get_encoding_settings(str(l))
        else:
            c = get_encoding_settings(str(l['height']), l['bitrateperc'])
        video_description = get_video_description(
            c['width'], c['height'], c['bitrate'], str(str(c['height']) + 'p' + str(c['bitrate'])), c['qvbr'])
        video_descriptions.append(video_description)
        output = get_output(str(str(c['height']) + 'p' + str(c['bitrate'])))
        outputs.append(output)
    channel_resp = medialive.create_channel(
        Name=channel_name,
        RoleArn=arn,
        InputAttachments=[{
            'InputId': input_id,
            'InputSettings': {
                "SourceEndBehavior": "LOOP",
                'NetworkInputSettings': {
                }
            }
        }],
        Destinations=[{
            'Id': 'destination1',
            'Settings': [
                {'Url': destinations['p_url'], 'Username': destinations['p_u'],
                    'PasswordParam': destinations['p_u']},
                {'Url': destinations['b_url'], 'Username': destinations['b_u'],
                    'PasswordParam': destinations['b_u']},

            ]
        }],
        EncoderSettings={
            'AudioDescriptions': [
                {
                    'AudioSelectorName': 'default',
                    'CodecSettings': {
                        'AacSettings': {
                            'InputType': 'NORMAL',
                            'Bitrate': 96000,
                            'CodingMode': 'CODING_MODE_2_0',
                            'RawFormat': 'NONE',
                            'Spec': 'MPEG4',
                            'Profile': 'LC',
                            'RateControlMode': 'CBR',
                            'SampleRate': 48000
                        }
                    },
                    'AudioTypeControl': 'FOLLOW_INPUT',
                    'LanguageCodeControl': 'FOLLOW_INPUT',
                    'Name': 'audio1',
                    'RemixSettings': {
                        'ChannelsIn': 2,
                        'ChannelsOut': 2,
                        'ChannelMappings': [
                            {'OutputChannel': 0, 'InputChannelLevels': [{'InputChannel': 0, 'Gain': 0}, {
                                'InputChannel': 1, 'Gain': -60}]},  # Left channel
                            {'OutputChannel': 1, 'InputChannelLevels': [
                                {'InputChannel': 0, 'Gain': -60}, {'InputChannel': 1, 'Gain': 0}]},  # Right channel
                        ]
                    }
                }
            ],
            'CaptionDescriptions': [],
            'OutputGroups': [
                {
                    'OutputGroupSettings': {
                        'HlsGroupSettings': {
                            'CaptionLanguageSetting': 'OMIT',
                            'CaptionLanguageMappings': [],
                            'ManifestCompression': 'NONE',
                            'Destination': {
                                'DestinationRefId': 'destination1'
                            },
                            'HlsCdnSettings': {
                                'HlsWebdavSettings': {}
                            },
                            "AdMarkers": [
                            "ELEMENTAL_SCTE35"
                            ],
                            'IvInManifest': 'INCLUDE',
                            'IvSource': 'FOLLOWS_SEGMENT_NUMBER',
                            'ClientCache': 'ENABLED',
                            'TsFileMode': 'SEGMENTED_FILES',
                            'ManifestDurationFormat': 'FLOATING_POINT',
                            'SegmentationMode': 'USE_SEGMENT_DURATION',
                            'OutputSelection': 'MANIFESTS_AND_SEGMENTS',
                            'StreamInfResolution': 'INCLUDE',
                            'IndexNSegments': 10,
                            'ProgramDateTime': 'EXCLUDE',
                            'KeepSegments': 21,
                            'MinSegmentLength': 0,
                            'SegmentLength': 6,
                            'TimedMetadataId3Frame': 'PRIV',
                            'TimedMetadataId3Period': 10,
                            'TimestampDeltaMilliseconds': 0,
                            'CodecSpecification': 'RFC_4281',
                            'DirectoryStructure': 'SINGLE_DIRECTORY',
                            'Mode': 'LIVE'
                        }
                    },
                    'Name': 'og1',
                    'Outputs': outputs
                }
            ],
            'TimecodeConfig': {
                'Source': 'EMBEDDED'
            },
            'VideoDescriptions': video_descriptions
        }
    )
    print(json.dumps(channel_resp))
    channel_id = channel_resp['Channel']['Id']
    return channel_id
    # return 'true'


