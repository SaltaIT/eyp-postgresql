import logging
import getopt
import sys
import subprocess
import os.path
import smtplib
import datetime, time
import psutil, os
import re
import socket
import urllib2
import getpass
import boto3
from os import access, R_OK
from ConfigParser import SafeConfigParser
from subprocess import Popen,PIPE,STDOUT
from email.MIMEMultipart import MIMEMultipart
from email.MIMEText import MIMEText
from random import randint

# puppet managed file

def sendReportEmail(errors, to_addr, id_host):
    global logFile

    from_addr=getpass.getuser()+'@'+socket.gethostname()

    msg = MIMEMultipart()
    msg['From'] = from_addr
    msg['To'] = to_addr
    if errors:
        msg['Subject'] = id_host+"-PGSNAPSHOT-ERROR"
    else:
        msg['Subject'] = id_host+"-PGSNAPSHOT-OK"

    body = "please check "+logFile+" on "+socket.gethostname()
    msg.attach(MIMEText(body, 'plain'))

    server = smtplib.SMTP('localhost')
    text = msg.as_string()
    server.sendmail(from_addr, to_addr, text)
    server.quit()

    logging.info("sent report to "+to_addr)

def isPostgresInBackupMode():
    # check if it is un backup mode
    # psql -U postgres -c 'select pg_backup_start_time();' | grep -A 1 -- --- | tail -n1
    p = subprocess.Popen("psql -U postgres -c 'select pg_backup_start_time();' | grep -A 1 -- --- | tail -n1", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    linecount=0
    lastline=""
    for line in p.stdout.readlines():
        lastline = line.strip()
        linecount+=1
    retval = p.wait()

    if retval==0 and linecount==1:
        return bool(lastline)
    else:
        logging.error('Unable check if postgres is on backup mode: '+lastline)

def logAndExit(msg):
    global purge
    global keep_lvm_snaps
    global vg_name
    global lv_name
    global keep_lvm_snaps
    global aws
    logging.debug("** EXIT MODE **")
    if isPostgresInBackupMode():
        logging.debug("** postgres in backup mode, disabling backup mode")
        postgresBackupMode(False)
    else:
        logging.debug("** postgres is not un backup mode")

    logging.error("** "+msg)

    if purge and keep_lvm_snaps==0:
        purgeOldLVMSnapshots(vg_name, lv_name, keep_lvm_snaps, aws)

    if to_addr:
        sendReportEmail(True, to_addr, id_host)

    sys.exit(msg+"\n")

def removeLVMSnapshot(lv_snap):
    p = subprocess.Popen("lvremove "+lv_snap+" -y", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    linecount=0
    lastline=""
    for line in p.stdout.readlines():
        lastline = line.strip()
        linecount+=1
    retval = p.wait()

    if retval==0 and linecount==1:
        logging.debug("removed snapshot:"+lv_snap)
        return lv_snap
    else:
        logAndExit('Unable to remove lvm snapshot: (retcode: '+str(retval)+')'+lastline)

def getLVMsnapshots(vg_name, lv_name):
    snaps = {}
    p = subprocess.Popen("lvdisplay /dev/"+vg_name+"/"+lv_name+" | awk '/LV snapshot/,/LV Status/' | grep -v LV | awk '{ print $1 }'", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    linecount=0
    for line in p.stdout.readlines():
        try:
            ts = time.mktime(datetime.datetime.strptime(line.strip(), snapshotbasename+'.'+timeformat).timetuple())
        except:
            continue
        snaps[ts] = line.strip()
    retval = p.wait()

    if retval==0:
        return snaps
    else:
        # not using longAndExit because we could end up in a recurse loop
        if to_addr:
            sendReportEmail(True, to_addr, id_host)

        sys.exit('Unable to purge old snapshots'+"\n")

def purgeOldLVMSnapshots(vg_name, lv_name, keep, aws):
    snaps = getLVMsnapshots(vg_name, lv_name)

    if len(snaps)!=0:
        keylist = snaps.keys()
        keylist.sort()
        logging.debug("keylist: "+str(keylist))
        to_delete = len(keylist)-keep
        if to_delete<0:
            to_delete=0
        logging.debug("snapshots: "+str(len(keylist))+" keeping: "+str(keep)+" deleting: "+str(to_delete))
        for key in keylist:
            if to_delete<=0:
                return True
            logging.debug("purging LVM snapshot: "+str(key)+": "+snaps[key])
            removeLVMSnapshot("/dev/"+vg_name+"/"+snaps[key])
            to_delete-=1
        return True
    else:
        # not using longAndExit because we could end up in a recurse loop
        if to_addr:
            sendReportEmail(True, to_addr, id_host)

        sys.exit('Unable to purge old snapshots'+"\n")

def doLVMSnapshot(lvm_disk, snap_name, snap_size='5G'):
    # [root@ip-172-31-46-9 ~]# lvcreate -s -n snap -L 5G /dev/vg/postgres
    #   Logical volume "snap" created.
    # [root@ip-172-31-46-9 ~]# echo $?
    # 0
    # [root@ip-172-31-46-9 ~]#
    p = subprocess.Popen("lvcreate -s -n "+snap_name+" -L "+snap_size+" "+lvm_disk+" 2>/dev/null", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    linecount=0
    output=""
    lastline=""
    for line in p.stdout.readlines():
        lastline = line.strip()
        output+=lastline
        linecount+=1
    retval = p.wait()

    if retval==0:
        logging.debug("created snapshot:"+snap_name)
        return snap_name
    else:
        logAndExit('Unable to create lvm snapshot (retcode: '+str(retval)+'): '+output)


def postgresBackupMode(enable = True, backup_name=""):
    global pgusername
    global snapshotbasename
    if enable:
        if not backup_name:
            backup_name = snapshotbasename+"."+datetime.datetime.fromtimestamp(time.time()).strftime(timeformat)
        backup_command ="select pg_start_backup('"+backup_name+"');"
    else:
        backup_command = "select pg_stop_backup();"

    psql_command = "psql -U "+pgusername+' -c "'+backup_command+'"'
    logging.debug("postgresBackupMode: "+psql_command)
    p = subprocess.Popen(psql_command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for line in p.stdout.readlines():
        logging.debug("postgresBackupMode: "+line.strip())
    retval = p.wait()

    if retval==0:
        return backup_name
    else:
        logAndExit('Unable to start pg_backup')

def getDisks(pv_disks, tranlate_aws=True):
    disks = set()
    regex = re.compile(r"^xv")
    for pv_disk in pv_disks:
        p = subprocess.Popen("lsblk -no pkname "+pv_disk+" | head -n1", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        linecount=0
        lastline=""
        for line in p.stdout.readlines():
            lastline = line.strip()
            linecount+=1
        retval = p.wait()

        if retval==0 and linecount==1:
            if tranlate_aws:
                disks.add("/dev/"+regex.sub('s', lastline))
            else:
                disks.add("/dev/"+lastline)
        else:
            logAndExit('Error getting disk from PV')
    return disks


# thank god for stackoverflow - https://stackoverflow.com/questions/25283882/determining-the-filesystem-type-from-a-path-in-python
def getFSType(path):
    partition = {}
    for part in psutil.disk_partitions(True):
        partition[part.mountpoint] = (part.fstype, part.device)
    if path in partition:
        return partition[path]
    splitpath = path.split(os.sep)
    for i in xrange(len(splitpath),0,-1):
        path = os.sep.join(splitpath[:i]) + os.sep
        if path in partition:
            return partition[path]
        path = os.sep.join(splitpath[:i])
        if path in partition:
            return partition[path]
    return ("unkown","none")

def getDataDir():
    global pgusername
    #psql -U postgres -c 'SHOW data_directory;'
    p = subprocess.Popen("psql -U "+pgusername+" -c 'SHOW data_directory;' | grep -A 1 -- --- | tail -n1", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    linecount=0
    lastline=""
    for line in p.stdout.readlines():
        lastline = line.strip()
        linecount+=1
    retval = p.wait()

    if retval==0 and linecount==1:
        return lastline
    else:
        logAndExit('Error getting datadir')

def getLV(lvm_disk):
    # busquem vg del lv, dsp pv del vg
    p = subprocess.Popen('lvdisplay '+lvm_disk+' 2>/dev/null | grep "LV Name"', shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    linecount=0
    lastline=""
    output=""
    for line in p.stdout.readlines():
        lastline = line
        linecount+=1
        output+=line
    retval = p.wait()

    if retval==0 and linecount==1:
        line_split = lastline.split()
        if line_split[0]=="LV" and line_split[1]=="Name":
            return line_split[2]
        else:
            logAndExit('Corrupted output getting LV name: '+lastline)
    else:
        logAndExit('Invalid disk '+lvm_disk+": "+output)

def getVG(lvm_disk):
    # busquem vg del lv, dsp pv del vg
    p = subprocess.Popen('lvdisplay '+lvm_disk+' 2>/dev/null | grep "VG Name"', shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    linecount=0
    lastline=""
    output=""
    for line in p.stdout.readlines():
        lastline = line
        linecount+=1
        output+=line
    retval = p.wait()

    if retval==0 and linecount==1:
        line_split = lastline.split()
        if line_split[0]=="VG" and line_split[1]=="Name":
            return line_split[2]
        else:
            logAndExit('Corrupted output getting VG name: '+lastline)
    else:
        logAndExit('Invalid disk '+lvm_disk+": "+output)

def getPVs(vg_name):
    pv_disks = []

    p = subprocess.Popen('vgdisplay '+vg_name+' -vv 2>/dev/null  | grep "PV Name"', shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for line in p.stdout.readlines():
        line_split = line.split()
        if line_split[0]=="PV" and line_split[1]=="Name":
            pv_disks.append(line_split[2])
        else:
            logAndExit('Corrupted output getting PV disk for '+vg_name)
    retval = p.wait()

    if retval!=0:
        logAndExit('ERROR listing PV disks for: '+vg_name)
    else:
        return pv_disks

def getInstanceID():
    return urllib2.urlopen('http://169.254.169.254/latest/meta-data/instance-id').read()

def getAWSVolumes(instance_devices):
    volumes = []
    for instance_device in instance_devices:
        if instance_device['DeviceName'] in disks:
            volumes.append(instance_device['Ebs']['VolumeId'])
    return volumes

def createAWSsnapshot(volume_id, lvm_disk, snap_name):
    global id_host
    try:
        ec2 = boto3.resource('ec2')
        logging.getLogger('boto3').setLevel(logging.CRITICAL)
        logging.getLogger('botocore').setLevel(logging.CRITICAL)
        logging.getLogger('nose').setLevel(logging.CRITICAL)
        # Create snapshot
        # response = ec2.create_snapshot(VolumeId=volume_id, Description="pgsnapshot for "+snap_name)
        # result = response[volume_id]
        # ec2.create_tags(Resources=[result],Tags=[{ 'Key': 'pgsnapshot-lvm_disk', 'Value': lvm_disk },{ 'Key': 'pgsnapshot-host', 'Value': id_host },{ 'Key': 'pgsnapshot-snap_name', 'Value': snap_name }])
        snapshot = ec2.create_snapshot(VolumeId=volume_id, Description="pgsnapshot for "+snap_name, TagSpecifications = [{
        'ResourceType': 'snapshot',
        'Tags': [
                    {'Key': 'Name', 'Value': snap_name }, { 'Key': 'pgsnapshot-lvm_disk', 'Value': lvm_disk },{ 'Key': 'pgsnapshot-host', 'Value': id_host },{ 'Key': 'pgsnapshot-snap_name', 'Value': snap_name }        ]
        }])
        #snapshot.add_tags({ 'Key': 'pgsnapshot-lvm_disk', 'Value': lvm_disk },{ 'Key': 'pgsnapshot-host', 'Value': id_host },{ 'Key': 'pgsnapshot-snap_name', 'Value': snap_name })
        # ec2.create_tags(
        #                     Resources=[
        #                         snapshot['SnapshotId'],
        #                     ],
        #                     Tags=[
        #                         { 'Key': 'pgsnapshot-lvm_disk', 'Value': lvm_disk },{ 'Key': 'pgsnapshot-host', 'Value': id_host },{ 'Key': 'pgsnapshot-snap_name', 'Value': snap_name }
        #                     ]
        #                 )
        return True
    except Exception as e:
        logging.error(str(e))
        return False

def getAWSsnapshot(id_host, lvm_disk, snap_name):
    # tag :<key> - The key/value combination of a tag assigned to the resource. Use the tag key in the filter name and the tag value as the filter value.
    # For example, to find all resources that have a tag with the key Owner and the value TeamA , specify tag:Owner for the filter name and TeamA for the filter value.
    try:
        ec2 = boto3.client('ec2')
        logging.getLogger('boto3').setLevel(logging.CRITICAL)
        logging.getLogger('botocore').setLevel(logging.CRITICAL)
        logging.getLogger('nose').setLevel(logging.CRITICAL)
        filter = [
                    {
                        'Name': 'tag:pgsnapshot-lvm_disk',
                        'Values': [
                            lvm_disk,
                        ]
                    },
                    {
                        'Name': 'tag:pgsnapshot-host',
                        'Values': [
                            id_host,
                        ]
                    },
                ]

        if snap_name:
            filter.append(
                            {
                                'Name': 'tag:pgsnapshot-snap_name',
                                'Values': [
                                    snap_name,
                                ]
                            }
                        )
        logging.debug("getAWSsnapshot::filter: "+str(filter))
        response = ec2.describe_snapshots(
            Filters=filter
        )

        return response['Snapshots']
    except Exception as e:
        logAndExit('error getting AWS snapshot list: '+str(e))


def purgeOldAWSsnapshots(id_host, lvm_disk, keep_days):
    logging.debug("purging old AWS snapshots, keep days: "+str(keep_days))
    aws_snapshots = getAWSsnapshot(id_host, lvm_disk, "")

    target_date = datetime.datetime.today() - datetime.timedelta(days=keep_days)
    target_date_ts = time.mktime(target_date.timetuple())

    logging.debug("purge target: "+str(target_date))
    logging.debug("purge target ts: "+str(target_date_ts))

    # {'ResponseMetadata': {'RetryAttempts': 0, 'HTTPStatusCode': 200, 'RequestId': '5177d80b-fe23-4df7-a650-3ebedf26e230', 'HTTPHeaders': {'date': 'Thu, 29 Nov 2018 09:32:30 GMT', 'content-type': 'text/xml;charset=UTF-8', 'content-length': '2253', 'vary': 'Accept-Encoding', 'server': 'AmazonEC2'}},
    # u'Snapshots': [
    # {u'Description': 'pgsnapshot for snap.20181129093229',
    # u'Tags': [{u'Value': 'ip-172-31-46-9.eu-west-1.compute.internal', u'Key': 'pgsnapshot-host'}, {u'Value': '/dev/mapper/vg-postgres', u'Key': 'pgsnapshot-lvm_disk'}, {u'Value': 'snap.20181129093229', u'Key': 'pgsnapshot-snap_name'}],
    #  u'Encrypted': False, u'VolumeId': 'vol-037ee28bd9bb1b9ac',
    #  u'State': 'pending', u'VolumeSize': 20,
    #  u'StartTime': datetime.datetime(2018, 11, 29, 9, 32, 30, tzinfo=tzlocal()),
    #   u'Progress': '28%', u'OwnerId': '237822962101', u'SnapshotId': 'snap-01e1ade665d6316cb'},
    # {u'Description': 'pgsnapshot for snap.20181129093229', u'Tags': [{u'Value': '/dev/mapper/vg-postgres', u'Key': 'pgsnapshot-lvm_disk'}, {u'Value': 'snap.20181129093229', u'Key': 'pgsnapshot-snap_name'}, {u'Value': 'ip-172-31-46-9.eu-west-1.compute.internal', u'Key': 'pgsnapshot-host'}], u'Encrypted': False, u'VolumeId': 'vol-0f1d6ecbf9c97c1bc', u'State': 'pending', u'VolumeSize': 10, u'StartTime': datetime.datetime(2018, 11, 29, 9, 32, 30, tzinfo=tzlocal()), u'Progress': '11%', u'OwnerId': '237822962101', u'SnapshotId': 'snap-0e9131a46617028e7'}]}

    logging.debug("list of snaps: "+str(aws_snapshots))
    logging.debug("//*//")
    old_snaps = []
    for aws_snapshot in aws_snapshots:
        logging.debug("inspecting "+aws_snapshot['SnapshotId'])
        if time.mktime(aws_snapshot['StartTime'].timetuple()) < target_date_ts:
            logging.debug("old //"+aws_snapshot['SnapshotId']+"// "+str(time.mktime(aws_snapshot['StartTime'].timetuple()))+" > "+str(target_date_ts))
            old_snaps.append(aws_snapshot)
        else:
            logging.debug("keeping: "+aws_snapshot['SnapshotId'])
    logging.debug("//*//")
    logging.debug("snaps to delete: "+str(old_snaps))

    ec2 = boto3.client('ec2')

    logging.getLogger('boto3').setLevel(logging.CRITICAL)
    logging.getLogger('botocore').setLevel(logging.CRITICAL)
    logging.getLogger('nose').setLevel(logging.CRITICAL)

    for aws_snapshot in old_snaps:
        logging.debug("purging AWS snapshot: "+aws_snapshot['SnapshotId'])
        ec2.delete_snapshot(SnapshotId=aws_snapshot['SnapshotId'])

def getInstance(instance_id):
    ec2 = boto3.resource('ec2')
    logging.getLogger('boto3').setLevel(logging.CRITICAL)
    logging.getLogger('botocore').setLevel(logging.CRITICAL)
    logging.getLogger('nose').setLevel(logging.CRITICAL)
    return ec2.Instance(instance_id)

def getVolumesFromSnapshot(id_host, lvm_disk, snap_name, snapshot_id=""):
    logging.debug("getVolumesFromSnapshot ("+id_host+", "+lvm_disk+", "+snap_name+", "+snapshot_id+")")
    client = boto3.client('ec2')
    filters = [
                {
                    'Name': 'tag:pgsnapshot-snap_name',
                    'Values': [
                        snap_name,
                    ]
                },
                {
                    'Name': 'tag:pgsnapshot-lvm_disk',
                    'Values': [
                        lvm_disk,
                    ]
                },
                {
                    'Name': 'tag:pgsnapshot-host',
                    'Values': [
                        id_host,
                    ]
                },
            ]

    if snapshot_id:
        filters.append(
                        {
                            'Name': 'snapshot-id',
                            'Values': [
                                snapshot_id,
                            ]
                        }
        )
    logging.debug("getVolumesFromSnapshot filters: "+str(filters))
    response = client.describe_volumes(
                                        Filters=filters
                                    )
    logging.debug("getVolumesFromSnapshot - client.describe_volumes response: "+str(response))
    return response

def createAWSVolumeFromSnapshotID(az, snapshot_id, id_host, lvm_disk, snap_name):
    logging.debug("createAWSVolumeFromSnapshotID("+az+", "+snapshot_id+", "+id_host+", "+lvm_disk+", "+snap_name+")")
    tags = [
        {
            'Key': 'Name',
            'Value': snap_name+" - "+snapshot_id,
        },
        {
            'Key': 'pgsnapshot-volume_created_from_snapshot',
            'Value': datetime.datetime.fromtimestamp(time.time()).strftime(timeformat),
        },
        {
            'Key': 'pgsnapshot-snap_name',
            'Value': snap_name,
        },
        {
            'Key': 'pgsnapshot-lvm_disk',
            'Value': lvm_disk,
        },
        {
            'Key': 'pgsnapshot-host',
            'Value': id_host,
        },
    ]
    logging.debug("createAWSVolumeFromSnapshotID tags: "+str(tags))
    ec2 = boto3.resource('ec2')
    volume = ec2.create_volume(
                                AvailabilityZone=az,
                                SnapshotId=snapshot_id,
                                VolumeType='gp2',
                                TagSpecifications=[
                                    {
                                        'ResourceType': 'volume',
                                        'Tags': tags
                                    },
                                ]
                            )
    return volume

def validateVolumesAreNotAttached(aws_volumes):
    logging.debug("validateVolumesAreNotAttached")
    for aws_volume in aws_volumes:
        attachments = aws_volume['Attachments']
        if(len(attachments)>0):
            logAndExit("volume "+aws_volume['VolumeId']+" already has "+str(len(attachments))+" attachments")
    logging.debug("validateVolumesAreNotAttached - all clear")

def waitForAWSRestoredInstance2bRunning(id_host, lvm_disk, snap_name):
    logging.debug("waitForAWSRestoredInstance2bRunning")
    instance_running=False
    while not instance_running:
        restored_instances = searchForRestoredInstance(id_host, lvm_disk, snap_name)
        for reservation in restored_instances:
            # logging.debug("reservation: "+str(reservation))
            for instance in reservation['Instances']:
                logging.debug("* "+instance['InstanceId']+": "+instance['State']['Name'])
                if instance['State']['Name']=='running':
                    instance_running=True
                if instance['State']['Name']=='pending':
                    instance_running=False
                    break
        if not instance_running:
            random_sleep = randint(10,100)
            logging.debug("waiting for AWS restore instance to startup for "+str(random_sleep)+" seconds")
            time.sleep(random_sleep)
    logging.debug("waitForAWSRestoredInstance2bRunning - all clear")

def waitForAWSRestoredInstanceVolumes2bAttached(id_host, lvm_disk, snap_name):
    logging.debug("waitForAWSRestoredInstanceVolumes2bAttached")
    volumes_attached=False
    while not volumes_attached:
        restored_instances = searchForRestoredInstance(id_host, lvm_disk, snap_name)

        logging.debug("checking instance status:")
        running_restores=0
        running_instance_id=""
        running_instance=None
        running_instance_region=None
        for reservation in restored_instances:
            # logging.debug("reservation: "+str(reservation))
            for instance in reservation['Instances']:
                logging.debug(instance['InstanceId']+": "+instance['State']['Name'])
                if instance['State']['Name']!='terminated' and instance['State']['Name']!='shutting-down' and instance['State']['Name']!='pending':
                    running_restores+=1
                    running_instance_id=instance['InstanceId']
                    running_instance=instance
                    running_instance_region=instance['Placement']['AvailabilityZone']

        if running_restores!=1 or not running_instance_id:
            logAndExit("too many restore VMs ("+str(running_restores)+"): "+str(restored_instances)+" - instance_id: "+running_instance_id)

        volumes_attached=True
        for device in running_instance['BlockDeviceMappings']:
            logging.debug("device: "+str(device))
            #    u'BlockDeviceMappings': [{u'DeviceName': '/dev/sda1', u'Ebs': {u'Status': 'attached', ...
            #                             {u'DeviceName': '/dev/sdo', u'Ebs': {u'Status': 'attaching' ...
            if device['Ebs']['Status']!="attached":
                random_sleep = randint(10,100)
                logging.debug("waiting for AWS volume "+device['DeviceName']+" to attach for "+str(random_sleep)+" seconds - current status: "+device['Ebs']['Status'])
                time.sleep(random_sleep)
                volumes_attached=False
    logging.debug("waitForAWSRestoredInstanceVolumes2bAttached - all clear")



def waitForAWSVolumes2bAvailable(aws_volumes):
    logging.debug("waitForAWSVolumes2bAvailable")
    client = boto3.client('ec2')
    for aws_volume in aws_volumes:
        response = client.describe_volume_status(VolumeIds=[aws_volume['VolumeId']])
        current_status = response['VolumeStatuses'][0]['VolumeStatus']['Status']
        logging.debug(aws_volume['VolumeId']+" status: "+current_status)
        if(current_status !='ok'):
            random_sleep = randint(10,100)
            logging.debug("waiting for AWS volume "+aws_volume['VolumeId']+" for "+str(random_sleep)+" seconds - current status: "+current_status)
            time.sleep(random_sleep)
    logging.debug("waitForAWSVolumes2bAvailable - all clear")

def createAWSVolumeFromSnapshotName(snap_name, id_host, lvm_disk, az):
    logging.debug("// createAWSVolumeFromSnapshotName")
    aws_snapshots = getAWSsnapshot(id_host, lvm_disk, snap_name)
    aws_volumes_response = getVolumesFromSnapshot(id_host, lvm_disk, snap_name)
    aws_volumes = aws_volumes_response['Volumes']

    logging.debug("1) AWS snapshots: "+str(aws_snapshots))
    logging.debug("1) AWS volumes: "+str(aws_volumes))

    if(len(aws_volumes)==len(aws_snapshots)) and len(aws_volumes)!=0:
        # suposem que la relacio es 1 a 1, aqui potencial bug com una casa
        logging.debug("createAWSVolumeFromSnapshotName:: ("+snap_name+"/"+id_host+"/"+lvm_disk+") - AWS VOLUMES: "+str(len(aws_volumes))+" vs "+"AWS SNAPSHOTS: "+str(len(aws_snapshots)))

        # TODO: verificar que no estan ja attachats
    else:
        # crear volums pels snapshots que no tenen volum
        for aws_snapshot in aws_snapshots:
            logging.debug("*X inspecting snapshot: "+aws_snapshot['SnapshotId'])
            aws_volumes_for_snapshot = getVolumesFromSnapshot(id_host, lvm_disk, snap_name, aws_snapshot['SnapshotId'])['Volumes']
            if(len(aws_volumes_for_snapshot))==0:
                logging.debug("creating volume using snaphot_id: "+aws_snapshot['SnapshotId'])
                volume = createAWSVolumeFromSnapshotID(az, aws_snapshot['SnapshotId'], id_host, lvm_disk, snap_name)
                logging.debug("created volume: "+volume.volume_id+" tags: "+str(volume.tags))
            else:
                logging.debug("snapshot with volumes:"+str(aws_volumes_for_snapshot))

        # un cop creats repeteixo query i retorno
        aws_volumes_response = getVolumesFromSnapshot(id_host, lvm_disk, snap_name)
        aws_volumes = aws_volumes_response['Volumes']

        logging.debug("2) AWS volumes: "+str(aws_volumes))

    while len(aws_volumes)==0:
        random_sleep = randint(30,120)
        logging.debug("waiting for AWS volumes to be created for "+str(random_sleep)+" seconds")
        time.sleep(random_sleep)
        aws_volumes_response = getVolumesFromSnapshot(id_host, lvm_disk, snap_name)
        aws_volumes = aws_volumes_response['Volumes']

    logging.debug("3) AWS volumes: "+str(aws_volumes))

    waitForAWSVolumes2bAvailable(aws_volumes)
    return aws_volumes

def searchForRestoredInstance(id_host, lvm_disk, snap_name):
    logging.debug("searchForRestoredInstance")
    client = boto3.client('ec2')
    filters = [
                {
                    'Name': 'tag:pgsnapshot-lvm_disk',
                    'Values': [
                        lvm_disk,
                    ]
                },
                {
                    'Name': 'tag:pgsnapshot-host',
                    'Values': [
                        id_host,
                    ]
                },
            ]

    if snap_name:
        filters.append(
                {
                    'Name': 'tag:pgsnapshot-snap_name',
                    'Values': [
                        snap_name,
                    ]
                },
        )
    response = client.describe_instances(Filters=filters)
    logging.debug("describe_instances response: "+str(response))
    reservations = response['Reservations']
    return reservations

def assignElasticIPs(id_host, lvm_disk, snap_name):
    logging.debug("assignElasticIPs")
    ec2 = boto3.resource('ec2')
    ec2_client = boto3.client('ec2')

    restored_instances = searchForRestoredInstance(id_host, lvm_disk, snap_name)

    for reservation in restored_instances:
        # logging.debug("reservation: "+str(reservation))
        for instance in reservation['Instances']:
            if instance['State']['Name']=='running':
                if not instance['PublicDnsName']:
                    allocated_addr = ec2_client.allocate_address(Domain='vpc')

                    response = ec2_client.associate_address(
                        AllocationId=allocated_addr['AllocationId'],
                        InstanceId=instance['InstanceId'],
                    )

def launchAWSInstanceBasedOnInstanceIDwithSnapshots(base_instance_id, snap_name, id_host, lvm_disk, force_ami):
    ec2 = boto3.resource('ec2')
    ec2_client = boto3.client('ec2')

    logging.getLogger('boto3').setLevel(logging.CRITICAL)
    logging.getLogger('botocore').setLevel(logging.CRITICAL)
    logging.getLogger('nose').setLevel(logging.CRITICAL)

    aws_base_instance = getInstance(base_instance_id)

    sgs=[]
    count=1
    for security_group in aws_base_instance.security_groups:
        logging.debug("* SG"+str(count)+": "+security_group['GroupName']+" ("+security_group['GroupId']+")")
        sgs.append(security_group['GroupId'])
        count+=1

    if force_ami:
        instance_image_id=force_ami
    else:
        instance_image_id=aws_base_instance.image_id

    logging.debug("* ImageID: "+instance_image_id)
    logging.debug("* InstanceType: "+aws_base_instance.instance_type)
    logging.debug("* KeyName: "+aws_base_instance.key_name)
    logging.debug("* subnet ID: "+aws_base_instance.subnet_id)

    aws_volumes = createAWSVolumeFromSnapshotName(snap_name, id_host, lvm_disk, aws_base_instance.placement['AvailabilityZone'])
    # validateVolumesAreNotAttached(aws_volumes)

    restored_instances = searchForRestoredInstance(id_host, lvm_disk, snap_name)

    running_restores=0
    running_instance_id=""
    running_instance=None
    running_instance_region=None
    logging.debug("launchAWSInstanceBasedOnInstanceIDwithSnapshots first check - checking instance status:")
    for reservation in restored_instances:
        # logging.debug("reservation: "+str(reservation))
        for instance in reservation['Instances']:
            logging.debug(instance['InstanceId']+": "+instance['State']['Name'])
            if instance['State']['Name']=='running':
                running_restores+=1
                running_instance_id=instance['InstanceId']
                running_instance=instance
                running_instance_region=instance['Placement']['AvailabilityZone']


    if running_restores==0:
        logging.debug("launching new AWS instance")
        instance = ec2.create_instances(
                                ImageId=instance_image_id,
                                InstanceType=aws_base_instance.instance_type,
                                KeyName=aws_base_instance.key_name,
                                SecurityGroupIds=sgs,
                                SubnetId=aws_base_instance.subnet_id,
                                UserData="""#!/bin/bash

                                curl -I https://raw.githubusercontent.com/jordiprats/puppet-masterless/master/setup.sh 2>/dev/null | grep "HTTP/1.1 200 OK"
                                while [ "$?" -ne 0 ];
                                do
                                    sleep 10s
                                    curl -I https://raw.githubusercontent.com/jordiprats/puppet-masterless/master/setup.sh 2>/dev/null | grep "HTTP/1.1 200 OK"
                                done

                                curl https://raw.githubusercontent.com/jordiprats/puppet-masterless/master/setup.sh | bash
                                /opt/puppet-masterless/localpuppetmaster.sh -d /tmp/lvm -r https://github.com/SaltaIT/eyp-lvm -s /tmp/lvm/modules/lvm/examples/base.pp
                                /opt/puppet-masterless/localpuppetmaster.sh -d /tmp/postgres -r https://github.com/SaltaIT/eyp-postgresql -s /tmp/postgres/modules/postgresql/examples/pgsnaprestore.pp
                                /usr/local/bin/pgsnaprestore.sh """+snap_name+"\n",
                                TagSpecifications=[
                                                    {
                                                        'ResourceType': 'instance',
                                                        'Tags': [
                                                            {
                                                                'Key': 'Name',
                                                                'Value': snap_name
                                                            },
                                                            {
                                                                'Key': 'pgsnapshot-snap_name',
                                                                'Value': snap_name,
                                                            },
                                                            {
                                                                'Key': 'pgsnapshot-lvm_disk',
                                                                'Value': lvm_disk,
                                                            },
                                                            {
                                                                'Key': 'pgsnapshot-host',
                                                                'Value': id_host,
                                                            },
                                                            {
                                                                'Key': 'pgsnapshot-instance_created',
                                                                'Value': datetime.datetime.fromtimestamp(time.time()).strftime(timeformat)
                                                            },
                                                        ]
                                                    },
                                                ],
                                MinCount=1, MaxCount=1
                            )

        logging.debug("instancia creada info: "+str(instance))
        restored_instances = searchForRestoredInstance(id_host, lvm_disk, snap_name)
        logging.debug("restored_instances: "+str(restored_instances))

        waitForAWSRestoredInstance2bRunning(id_host, lvm_disk, snap_name)

        logging.debug("launched instance - checking instance status:")
        running_restores=0
        for reservation in restored_instances:
            # logging.debug("reservation: "+str(reservation))
            for instance in reservation['Instances']:
                logging.debug(instance['InstanceId']+": "+instance['State']['Name'])
                if instance['State']['Name']=='running':
                    running_restores+=1
                    running_instance_id=instance['InstanceId']
                    running_instance=instance
                    running_instance_region=instance['Placement']['AvailabilityZone']

    while_counter=0
    # assert: running restores ha de ser 1
    while running_restores!=1 or not running_instance_id:
        while_counter+=1
        random_sleep = randint(10,100)
        logging.debug("waiting for AWS restored instance (pre volume attach) to be running for "+str(random_sleep)+" seconds")
        time.sleep(random_sleep)

        waitForAWSRestoredInstance2bRunning(id_host, lvm_disk, snap_name)
        restored_instances = searchForRestoredInstance(id_host, lvm_disk, snap_name)
        logging.debug(str(while_counter)+" - checking instance status:")
        running_restores=0
        for reservation in restored_instances:
            # logging.debug("reservation: "+str(reservation))
            for instance in reservation['Instances']:
                logging.debug(instance['InstanceId']+": "+instance['State']['Name'])
                if instance['State']['Name']=='running':
                    running_restores+=1
                    running_instance_id=instance['InstanceId']
                    running_instance=instance
                    running_instance_region=instance['Placement']['AvailabilityZone']

        if running_restores>1:
            logAndExit("## "+str(running_restores)+" running restores, aborting")


    assignElasticIPs(id_host, lvm_disk, snap_name)

    #
    # Linux Devices: /dev/sdf through /dev/sdp
    #
    allowed_devices = ["/dev/sd"+chr(x) for x in range(102, 113)]

    for device in running_instance['BlockDeviceMappings']:
        logging.debug("device: "+str(device))
        if device['DeviceName'] in allowed_devices:
            allowed_devices.remove(device['DeviceName'])

    logging.debug("allowed_devices: "+str(allowed_devices))

    if not allowed_devices:
        logAndExit("allowed devices empty - unable to attach volumes to instance")

    logging.debug("list of aws volumes: "+str(aws_volumes))

    ec2_client=boto3.client('ec2')
    for aws_volume in aws_volumes:
        logging.debug("//*// aws_volume: "+str(aws_volume))
        is_attached=False
        for attachment in aws_volume['Attachments']:
            if attachment['InstanceId']==running_instance_id:
                is_attached=True
        # result = running_instance.attach_volume (VolumeId=aws_volume['VolumeId'], Device=allowed_devices.pop())
        if not is_attached:
            result = ec2_client.attach_volume(Device=allowed_devices.pop(), InstanceId=running_instance_id, VolumeId=aws_volume['VolumeId'])
            logging.debug("volume "+aws_volume['VolumeId']+" attachment result: "+str(result))
        else:
            logging.debug("volume "+aws_volume['VolumeId']+" is already attached")

    waitForAWSRestoredInstanceVolumes2bAttached(id_host, lvm_disk, snap_name)

    restored_instances = searchForRestoredInstance(id_host, lvm_disk, snap_name)
    logging.debug("restored_instances after attaching volumes: "+str(restored_instances))


    for reservation in restored_instances:
        # logging.debug("reservation: "+str(reservation))
        for instance in reservation['Instances']:
            if instance['State']['Name']=='running':
                if instance['PublicDnsName']:
                    print(instance['InstanceId']+": "+instance['PublicDnsName'])
                else:
                    print(instance['InstanceId']+": "+instance['PrivateDnsName'])
                break

def listAWSsnapshots():
    aws_snapshots = getAWSsnapshot(id_host, lvm_disk, "")

    logging.debug("snapshots: "+str(aws_snapshots))

    avaiable_backups={}

    for aws_snapshot in aws_snapshots:
        for aws_snapshot_tag in aws_snapshot['Tags']:
            if aws_snapshot_tag['Key']=='pgsnapshot-snap_name':
                if aws_snapshot_tag['Value'] in avaiable_backups:
                    avaiable_backups[aws_snapshot_tag['Value']].append(aws_snapshot['SnapshotId'])
                else:
                    avaiable_backups[aws_snapshot_tag['Value']]=[aws_snapshot['SnapshotId']]

    return avaiable_backups

def showJelp(msg):
    print("""
                ``        ,#
              @@@@@@      @@,
             #@@@@@@#    @@@
             @@@@@@@@   +@@@
            `@@@@@@@@` `@@@
            `@@@@@@@@` @@@#
             @@@@@@@@ #@@@
             #@@@@@@#.@@@+
     .@@@#    +@@@@+ @@@@
     .@@@@@@@+. ``  @@@@;
      .@@@@@@@@@@@@@@@@@
         :@@@@@@@@@@@@@@
            +@@@@@@@@@@@`
               @@@@@@@@@@
                ;@@@@@@@@
                 @@@@@@@@
                 @@@@@@@@#
                 @@@@@@@@@
                 +@@@@@@@@
                 ;@@@@@@@@
                 :@@@@@@@@
                 :@@@@@@@@
                 ,@@@@@@@@
                  @@@@@@@@@
                  @@@@@@@@@
                  @@@@@@@@@`
                 .@@@@ @@@@+
                 :@@@@ ;@@@@
                 #@@@, ,@@@@
          +@@;   @@@@  @@@@@
          @@@@@@@@@@@  @@@@@
          ;@@@@@@@@@   ;@@@@
            @@@@@@@+    +@@@
              `'@'

pgsnapshot - Into the snapshots to save the data!
    """)
    print("Usage:")
    print("* Global options:")
    print("   [-c|--config] <config file>")
    print("   [-a|--aws]")
    print("   [-d|--dontpurge]")
    print("   [-g|--logdir] <log dir>")
    print("   [-l|--lvm-disk] <lvm disk>")
    print("   [-s|--snapshot-size] <size>")
    print("   [-k|--keep-aws-snaps-days] <days>")
    print("   [-K|--keep-lvm-snaps] <number of LVM snapshots to keep>")
    print("* Modes:")
    print("   [-L|--list-backups]")
    print("   [-R|--list-restored-instances]")
    print("   [-r|--restore-to-vm] <snap>")
    print("")
    sys.exit(msg)

timeformat = '%Y%m%d%H%M%S'
lvm_disk = ""
snap_size = "5G"
aws = False
purge = True
config_file = './postgres_snapshot.config'
logdir = '/var/log/pgsnapshot'
pgusername = "postgres"
keep_lvm_snaps = 2
keep_aws_snaps_days = 7
snapshotbasename='snap'
error_count=0
restore_to_vm=""
list_backups=False
force_ami=""
list_retored_instances=False
debug=False

# parse opts
try:
    options, remainder = getopt.getopt(sys.argv[1:], 'l:s:ac:dk:r:LDhK:A:R', [
                                                                'lvm-disk=',
                                                                "config="
                                                                'snapshot-size=',
                                                                'aws',
                                                                'dontpurge',
                                                                'keep-aws-snaps-days=',
                                                                'restore-to-vm=',
                                                                'list-backups',
                                                                'debug',
                                                                'keep-lvm-snaps=',
                                                                'force-ami=',
                                                                'list-restored-instances'
                                                                'help'
                                                             ])
except Exception, e:
    showJelp(str(e))

for opt, arg in options:
    if opt in ('-l', '--lvm-disk'):
        lvm_disk = arg
    elif opt in ('-s', '--snapshot-size'):
        snap_size = arg
    elif opt in ('-k', '--keep_aws_snaps_days'):
        keep_aws_snaps_days = int(arg)
    elif opt in ('-K', '--keep-lvm-snaps'):
        keep_lvm_snaps = int(arg)
    elif opt in ('-c', '--config'):
        config_file = arg
    elif opt in ('-a', '--aws'):
        aws = True
    elif opt in ('-d', '--dontpurge'):
        purge = False
    elif opt in ('-R', '--list-restored-instances'):
        list_retored_instances = True
    elif opt in ('-L', '--list-backups'):
        list_backups = True
    elif opt in ('-D', '--debug'):
        debug = True
    elif opt in ('-g', '--logdir'):
        logdir = arg
    elif opt in ('-r', '--restore-to-vm'):
        restore_to_vm = arg
    elif opt in ('-A', '--force-ami'):
        force_ami = arg
    else:
        showJelp("")

logFormatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s")
rootLogger = logging.getLogger()

consoleHandler = logging.StreamHandler()
consoleHandler.setFormatter(logFormatter)
rootLogger.addHandler(consoleHandler)

if not os.path.isfile(config_file):
    logging.error("Error - config file NOT FOUND ("+config_file+")")
    sys.exit(1)

if not access(config_file, R_OK):
    logging.error("Error reading config file ("+config_file+")")
    sys.exit(1)

try:
    config = SafeConfigParser()
    config.read(config_file)
except Exception, e:
    logging.error("error reading config file - ABORTING - "+str(e))
    sys.exit(1)

try:
    logdir=config.get('pgsnapshot', 'logdir').strip('"')
except:
    logging.debug('Using default value for logdir: '+logdir)

ts = time.time()

logFile = "{0}/{1}/{2}-{3}.log".format(logdir, datetime.datetime.fromtimestamp(ts).strftime('%Y%m%d'), 'pgsnapshot', datetime.datetime.fromtimestamp(ts).strftime('%Y%m%d-%H%M%S'))

current_day_dirname = os.path.dirname(logFile)

try:
    os.makedirs(current_day_dirname)
except Exception, e:
    logging.debug("WARNING - error creating log directory: "+current_day_dirname+" - "+str(e))

fileHandler = logging.FileHandler(logFile)
fileHandler.setFormatter(logFormatter)
rootLogger.addHandler(fileHandler)

if debug:
    rootLogger.setLevel(0)
else:
    rootLogger.setLevel(40)

try:
    lvm_disk=config.get('pgsnapshot', 'lvmdisk').strip('"')
except:
    logging.debug('Using default value for lvm_disk: "'+lvm_disk+'"')

try:
    snap_size=config.get('pgsnapshot', 'snapsize').strip('"')
except:
    logging.debug('Using default value for snap_size: '+str(snap_size))

try:
    pgusername=config.get('pgsnapshot', 'pgusername').strip('"')
except:
    logging.debug('Using default value for pgusername: '+pgusername)

try:
    snapshotbasename=config.get('pgsnapshot', 'snapshotbasename').strip('"')
except:
    logging.debug('Using default value for snapshotbasename: '+snapshotbasename)

try:
    aws=config.getboolean('pgsnapshot', 'aws')
except:
    logging.debug('Using default value for aws: '+str(aws))

try:
    keep_lvm_snaps=int(config.get('pgsnapshot', 'keeplvmsnaps'))
except:
    if aws:
        keep_lvm_snaps=0
    else:
        keep_lvm_snaps=2

try:
    keep_aws_snaps_days=int(config.get('pgsnapshot', 'keepAWSsnapdays'))
except:
    logging.debug('Using default value for keep_aws_snaps_days: '+str(keep_aws_snaps_days))

try:
    to_addr=config.get('pgsnapshot', 'to').strip('"')
except:
    to_addr=''

try:
    id_host=config.get('pgsnapshot', 'host-id').strip('"')
except:
    id_host=socket.gethostname()

try:
    force_ami=config.get('pgsnapshot', 'force-ami').strip('"')
except:
    logging.debug('Using default value for force_ami: '+force_ami)

#
# ACTIONS
#

logging.debug(">> ACTIONS <<")

if not lvm_disk:
    logging.debug("lvm_disk undefined, searching datadir")
    datadir = getDataDir()
    logging.debug("postgres datadir: "+datadir)
    lvm_disk = getFSType(datadir)[1]

logging.debug("lvm_disk: "+lvm_disk)

lv_name = getLV(lvm_disk)

logging.debug("lv_name: "+lv_name)

vg_name = getVG(lvm_disk)

logging.debug("vg_name: "+vg_name)

pv_disks = getPVs(vg_name)

logging.debug("pv_disks: "+str(pv_disks))

disks = getDisks(pv_disks)

logging.debug("disks: "+str(disks))

if list_retored_instances:
    to_addr=""
    #
    # LIST RESTORED INSTANCES
    #
    restored_instances = searchForRestoredInstance(id_host, lvm_disk, '')
    logging.debug("//*// list restored instances: "+str(restored_instances))

    list_restored_instances_dnsname={}
    list_restored_instances_instance_id={}

    for instance in restored_instances[0]['Instances']:
        logging.debug(str(instance))
        logging.debug(instance['InstanceId']+": "+instance['State']['Name'])
        if instance['State']['Name']=='running':
            logging.debug("*X - instance "+instance['InstanceId']+": tags: "+str(instance['Tags']))
            for tag in instance['Tags']:
                if tag['Key']=="pgsnapshot-snap_name":
                    logging.debug("FOUND snaptag: "+tag['Value'])
                    if instance['PublicDnsName']:
                        list_restored_instances_dnsname[tag['Value']]=instance['PublicDnsName']
                    else:
                        list_restored_instances_dnsname[tag['Value']]=instance['PrivateDnsName']
                    list_restored_instances_instance_id[tag['Value']]=instance['InstanceId']

    logging.debug("llista restore instances dnsname: "+str(list_restored_instances_dnsname))
    logging.debug("llista restore instances instance_id: "+str(list_restored_instances_instance_id))

    keylist = list_restored_instances_dnsname.keys()
    keylist.sort()

    for backup in keylist:
        print(" * "+backup+": "+list_restored_instances_dnsname[backup]+" ("+list_restored_instances_instance_id[backup]+")")
    print("\n")

elif list_backups:
    to_addr=""
    #
    # LIST AVAILABLE BACKUPS
    #
    if aws:
        logging.debug("== LIST AWS BACKUPS ==")

        avaiable_backups = listAWSsnapshots()
        keylist = avaiable_backups.keys()
        keylist.sort()

        logging.debug("list of available backups: "+str(keylist))


        for backup in keylist:
            print(" * "+backup)
        print("\n")

    else:
        logging.debug("== LIST LVM BACKUPS ==")

        snaps = getLVMsnapshots(vg_name, lv_name)

        keylist = snaps.keys()
        keylist.sort()
        logging.debug(keylist)

        for key in keylist:
            print(" * "+snaps[key])
        print("\n")


elif restore_to_vm:
    to_addr=""
    if aws:
        #
        # RESTORE TO VM MODE
        #
        logging.debug("== RESTORE TO VM MODE ==")

        instance_id = getInstanceID()

        logging.debug('original instance_id: '+instance_id)

        aws_snapshots = getAWSsnapshot(id_host, lvm_disk, restore_to_vm)
        if len(aws_snapshots)>0:
            logging.debug('aws_snapshots: '+str(aws_snapshots))
            launchAWSInstanceBasedOnInstanceIDwithSnapshots(instance_id, restore_to_vm, id_host, lvm_disk, force_ami)
        else:
            logAndExit("unable to restore to VM using "+restore_to_vm)
    else:
        logAndExit("unable to restore LVM backup to VM")

else:
    #
    # BACKUP MODE
    #
    logging.debug("== BACKUP MODE ==")

    backup_name = postgresBackupMode(True)

    logging.debug("backup_name: "+backup_name)

    snap_name = doLVMSnapshot(lvm_disk, backup_name, snap_size)

    logging.debug("snap_name: "+snap_name)

    postgresBackupMode(False)

    if aws:
        try:
            logging.getLogger('boto3').setLevel(logging.CRITICAL)
            logging.getLogger('botocore').setLevel(logging.CRITICAL)
            logging.getLogger('nose').setLevel(logging.CRITICAL)

            instance_id = getInstanceID()

            logging.debug('instance_id: '+instance_id)

            if not instance_id:
              logAndExit("error getting instance_id")

            aws_instance = getInstance(instance_id)

            instance_devices = aws_instance.block_device_mappings

            logging.debug('instance_devices: '+str(instance_devices))

            volumes = getAWSVolumes(instance_devices)

            logging.debug('volumes: '+str(volumes))

            for volume_id in volumes:
                if createAWSsnapshot(volume_id, lvm_disk, snap_name):
                    logging.debug('created AWS snapshot for '+volume_id)
                else:
                    error_count+=0
                    logging.debug('error creating snapshot for '+volume_id)

            # wait for snapshots to be created
            aws_snapshots_pending=99
            while aws_snapshots_pending!=0:
                aws_snapshots = getAWSsnapshot(id_host, lvm_disk, snap_name)
                aws_snapshots_pending=0
                current_status = {}
                for aws_snapshot in aws_snapshots:
                    if aws_snapshot['State']=='pending':
                        aws_snapshots_pending+=1
                        current_status[aws_snapshot['SnapshotId']]=aws_snapshot['State']
                if aws_snapshots_pending!=0:
                    random_sleep = randint(10,100)
                    logging.debug("waiting for AWS snapshot for "+str(random_sleep)+" seconds - current status: "+str(current_status))
                    time.sleep(random_sleep)

            # validacio snapshots
            for aws_snapshot in aws_snapshots:
                if aws_snapshot['State']=='error':
                    error_count+=1

            if purge:
                purgeOldAWSsnapshots(id_host, lvm_disk, keep_aws_snaps_days)


        except Exception as e:
            logAndExit('error using AWS API: '+str(e))

    if purge:
        purgeOldLVMSnapshots(vg_name, lv_name, keep_lvm_snaps, aws)

    if to_addr:
        sendReportEmail(error_count!=0, to_addr, id_host)

    #
    # END BACKUP MODE
    #
