import logging
import stat
import pwd
import grp
import time
import csv
import tempfile
import os
import re
import shutil
import csv

from sets import Set
from ldif import LDIFWriter
from utils import *

INFO_SERVICE_CONFIG = "/etc/glite/info/service"
INFO_SERVICE_SCRIPT = "/usr/bin"
INFO_PROVIDER_PATH = "/var/lib/bdii/gip/provider"
INFO_LDIF_PATH = "/var/lib/bdii/gip/ldif"
INFO_PLUGIN_PATH = "/var/lib/bdii/gip/plugin"

class Glue2:

    GLUE2_INFO_SERVICE = INFO_SERVICE_SCRIPT + "/glite-info-glue2-simple"
    GLUE2_SERVICE_FILE = INFO_PROVIDER_PATH + "/service-glue2-srm-storm-v2"
    GLUE2_SERVICE_CONFIG_FILE = INFO_SERVICE_CONFIG + "/glite-info-service-glue2-srm-storm-v2.conf"
    GLUE2_STATIC_LDIF_FILE = INFO_LDIF_PATH + "/static-file-glue2-storm.ldif"
    GLUE2_INFO_PLUGIN_FILE = INFO_PLUGIN_PATH + "/glite-info-glue2-dynamic-storm"

    TEMPLATES_DIR = "/etc/storm/info-provider/templates/glue2"

    def __init__(self):
        self.creation_time = time.strftime('%Y-%m-%dT%T')
        self.baseDN = "GLUE2GroupID=resource,o=glue"
        self.access_protocols_versions = { 
            'file': '1.0.0', 
            'rfio': '1.0.0', 
            'gsiftp': '2.0.0', 
            'root': '1.0.0', 
            'http': '1.1.0', 
            'https': '1.1.0' 
        }
        self.quality_levels = ["development", "pre-production", "production", "testing"]
        return

    def init(self, configuration, stats):
        # GLUE2_SERVICE_FILE
        logging.debug("Creating %s ...", self.GLUE2_SERVICE_FILE)
        self.create_service_file(configuration)
        logging.info("Successfully created %s !", self.GLUE2_SERVICE_FILE)
        # GLUE2_SERVICE_CONFIG_FILE
        logging.debug("Creating %s ...", self.GLUE2_SERVICE_CONFIG_FILE)
        self.create_service_config_file(configuration, stats)
        logging.info("Successfully created %s !", self.GLUE2_SERVICE_CONFIG_FILE)
        # GLUE2_STATIC_LDIF_FILE
        logging.debug("Creating %s ...", self.GLUE2_STATIC_LDIF_FILE)
        created_file = self.create_static_ldif_file(configuration, stats)
        logging.info("Successfully created %s !", created_file)
        # GLUE2_PLUGIN_FILE
        logging.debug("Creating %s ...", self.GLUE2_INFO_PLUGIN_FILE)
        self.create_plugin_file()
        logging.info("Successfully created %s !", self.GLUE2_INFO_PLUGIN_FILE)
        # remove old cron file
        self.remove_old_cron_file_if_exists()
        return

    def create_service_file(self, configuration):
        srm_endpoint = "httpg://" + configuration["STORM_FRONTEND_PUBLIC_HOST"] + ":" + configuration["STORM_FRONTEND_PORT"] + configuration["STORM_FRONTEND_PATH"]
        f = open(self.GLUE2_SERVICE_FILE, "w")
        f.write("#!/bin/sh\n")
        f.write(". /etc/profile.d/grid-env.sh\n")
        f.write("%s %s " % (self.GLUE2_INFO_SERVICE, self.GLUE2_SERVICE_CONFIG_FILE))
        f.write("%s %s\n" % (configuration['SITE_NAME'], srm_endpoint))
        f.close()
        # Set execute permissions: chmod +x
        os.chmod(self.GLUE2_SERVICE_FILE, 0755)
        return self.GLUE2_SERVICE_FILE

    def create_service_config_file(self, configuration, stats):
        content = self.get_service_configuration(configuration, self.get_vos(stats["sas"]))
        f = open(self.GLUE2_SERVICE_CONFIG_FILE, "w")
        for key, val in content.items():
            f.write("%s=%s\n" % (key, val))
        f.close()
        # set owner
        uid = pwd.getpwnam("ldap").pw_uid
        gid = grp.getgrnam("ldap").gr_gid
        os.chown(self.GLUE2_SERVICE_CONFIG_FILE, uid, gid)
        return

    def create_plugin_file(self):
        conf_file_path = "/etc/storm/backend-server/storm-yaim-variables.conf"
        f = open(self.GLUE2_INFO_PLUGIN_FILE, "w")
        f.write("#!/bin/sh\n")
        f.write("/usr/libexec/storm-dynamic-info-provider/glite-info-glue2-dynamic-storm %s\n" % conf_file_path)
        f.close()
        # set owner
        uid = pwd.getpwnam("ldap").pw_uid
        gid = grp.getgrnam("ldap").gr_gid
        os.chown(self.GLUE2_INFO_PLUGIN_FILE, uid, gid)
        os.chmod(self.GLUE2_INFO_PLUGIN_FILE, 0755)
        return

    def create_static_ldif_file(self, configuration, stats):

        # Create and open tmp file
        target = tempfile.mkstemp()
        logging.debug("Created temporary file '%s'...", target[1])
        f = os.fdopen(target[0], "w")
        # Init LDIF writer
        ldif_writer = LDIFWriter(f, cols=512)

        # Glue2StorageService
        GLUE2DomainID = configuration["SITE_NAME"]
        GLUE2ServiceID = "glue:" + configuration["STORM_FRONTEND_PUBLIC_HOST"] + "/data"
        (dn, entry) = self.get_GLUE2StorageService(GLUE2ServiceID, GLUE2DomainID, self.quality_levels[int(configuration['STORM_ENDPOINT_QUALITY_LEVEL'])])
        ldif_writer.unparse(dn, entry)

        # Glue2StorageServiceCapacity online
        if stats["summary"]["total-space"] > 0:
            GLUE2StorageServiceCapacityID = GLUE2ServiceID + "/ssc/disk"
            (dn, entry) = self.get_GLUE2StorageServiceCapacity(GLUE2StorageServiceCapacityID, GLUE2ServiceID, "online", 
                round_div(stats["summary"]["total-space"],1000000000), round_div(stats["summary"]["free-space"],1000000000),
                round_div(stats["summary"]["used-space"],1000000000), round_div(stats["summary"]["reserved-space"],1000000000))
            ldif_writer.unparse(dn, entry)

        # Glue2StorageServiceCapacity nearline
        if stats["summary"]["nearline-space"] > 0:
            GLUE2StorageServiceCapacityID = GLUE2ServiceID + "/ssc/tape"
            (dn, entry) = self.get_GLUE2StorageServiceCapacity(GLUE2StorageServiceCapacityID, GLUE2ServiceID, "nearline", 
                round_div(stats["summary"]["nearline-space"],1000000000), 0, 0, 0)
            ldif_writer.unparse(dn, entry)

        # GLUE2StorageAccessProtocol for each protocol
        protocol_versions = self.get_enabled_protocols(configuration)
        for protocol in protocol_versions:
            GLUE2StorageAccessProtocolID = GLUE2ServiceID + "/ap/" + protocol + "/" + protocol_versions[protocol]
            (dn, entry) = self.get_GLUE2StorageAccessProtocol(GLUE2StorageAccessProtocolID, GLUE2ServiceID, protocol, protocol_versions[protocol])
            ldif_writer.unparse(dn, entry)

        # Glue2StorageManager
        GLUE2ManagerID = GLUE2ServiceID + "/m/StoRM"
        (dn, entry) = self.get_GLUE2StorageManager(GLUE2ManagerID, GLUE2ServiceID)
        ldif_writer.unparse(dn, entry)

        # Glue2DataStore
        if stats["summary"]["total-space"] > 0:
            # Glue2DataStore disk online
            GLUE2ResourceID = GLUE2ServiceID + "/ds/StoRM/disk"
            (dn, entry) = self.get_GLUE2DataStore(GLUE2ResourceID, GLUE2ManagerID, GLUE2ServiceID, "disk", "online", round_div(stats["summary"]["total-space"],1000000000))
            ldif_writer.unparse(dn, entry)

        if stats["summary"]["nearline-space"] > 0:
            # Glue2DataStore tape nearline
            GLUE2ResourceID = GLUE2ServiceID + "/ds/StoRM/tape"
            (dn, entry) = self.get_GLUE2DataStore(GLUE2ResourceID, GLUE2ManagerID, GLUE2ServiceID, "tape", "nearline", round_div(stats["summary"]["nearline-space"],1000000000))
            ldif_writer.unparse(dn, entry)

        # Glue2Share, GLUE2MappingPolicy and Glue2StorageShareCapacity for each VFS
        for sa_name in stats["sas"]:
            sa_data = stats["sas"][sa_name]

            # GLUE2Share
            GLUE2ShareID = GLUE2ServiceID + "/ss/" + sa_data["name"]
            sharingID = ":".join((sa_data["voname"],sa_data["retentionPolicy"],sa_data["accessLatency"]))
            if "*" in sa_data["voname"]:
                sharingID = "dedicated"                
            (dn, entry) = self.get_GLUE2StorageShare(GLUE2ShareID, GLUE2ServiceID, sa_data["accessLatency"].lower(), sa_data["retentionPolicy"].lower(), "production", sharingID)
            ldif_writer.unparse(dn, entry)

            # GLUE2MappingPolicy
            GLUE2PolicyID = GLUE2ShareID + "/mp/basic"
            user_domain = sa_data["voname"]
            if "*" in sa_data["voname"]:
                user_domain = "anonymous" 
            (dn, entry) = self.get_GLUE2MappingPolicy(GLUE2PolicyID, GLUE2ShareID, GLUE2ServiceID, user_domain, sa_data["approachableRules"])
            ldif_writer.unparse(dn, entry)
            
            # Glue2StorageShareCapacity
            GLUE2StorageShareCapacityID = GLUE2ShareID + "/disk"
            (dn, entry) = self.get_GLUE2StorageShareCapacity(GLUE2StorageShareCapacityID, GLUE2ShareID, GLUE2ServiceID, sa_data["accessLatency"].lower(), 
                round_div(sa_data["total-space"],1000000000), round_div(sa_data["free-space"],1000000000), round_div(sa_data["used-space"],1000000000),
                round_div(sa_data["reserved-space"],1000000000))
            ldif_writer.unparse(dn, entry)

        vos = self.get_vos(stats["sas"])

        # Glue2StorageEndpoint - frontend list
        frontend_host_list = configuration["STORM_FRONTEND_HOST_LIST"].split(',')
        # SRM endpoints
        GLUE2EndpointInterfaceName = "SRM"
        GLUE2EndpointInterfaceVersion = "2.2.0"
        GLUE2EndpointTechnology = "webservice"
        GLUE2EndpointQualityLevel = self.quality_levels[int(configuration['STORM_ENDPOINT_QUALITY_LEVEL'])]
        GLUE2EndpointServingState = "production"
        GLUE2EndpointCapability = ["data.management.storage"]

        for frontend_host in frontend_host_list:
            # Glue2StorageEndpoint SRM
            GLUE2EndpointID = GLUE2ServiceID + "/ep/" + frontend_host + ":" + configuration["STORM_FRONTEND_PORT"] + "/" + GLUE2EndpointInterfaceName + "/" + GLUE2EndpointInterfaceVersion
            GLUE2EndpointURL = "httpg://" + frontend_host + ":" + configuration["STORM_FRONTEND_PORT"] + configuration["STORM_FRONTEND_PATH"]
            GLUE2EntityOtherInfo = []
            for protocol in protocol_versions:
                GLUE2EntityOtherInfo.append("SupportedProtocol=" + protocol)
            (dn, entry) = self.get_GLUE2StorageEndpoint(GLUE2EndpointID, GLUE2ServiceID, GLUE2EndpointURL, GLUE2EntityOtherInfo, GLUE2EndpointTechnology, GLUE2EndpointInterfaceName, 
                GLUE2EndpointInterfaceVersion, GLUE2EndpointQualityLevel, GLUE2EndpointServingState, GLUE2EndpointCapability)
            ldif_writer.unparse(dn, entry)
            # Glue2AccessPolicy for the endpoint
            GLUE2PolicyID = GLUE2EndpointID + "/ap/basic"
            GLUE2AccessPolicyRule = []
            for vo in vos:
                GLUE2AccessPolicyRule.append("vo:" + vo)
            (dn, entry) = self.get_GLUE2AccessPolicy(GLUE2PolicyID, GLUE2EndpointID, GLUE2ServiceID, GLUE2AccessPolicyRule)
            ldif_writer.unparse(dn, entry)

        if configuration['STORM_GRIDHTTPS_ENABLED'].lower() == "true":

            # Glue2StorageEndpoint - gridhttps list
            gridhttps_host_list = configuration["STORM_GRIDHTTPS_POOL_LIST"].split(',')
            GLUE2EndpointInterfaceVersion = "1.1"
            GLUE2EndpointTechnology = "webservice"
            GLUE2EndpointQualityLevel = self.quality_levels[int(configuration['STORM_ENDPOINT_QUALITY_LEVEL'])]
            GLUE2EndpointServingState = "production"
            GLUE2EntityOtherInfo = ["SupportedProtocol=WebDAV"]
            GLUE2EndpointCapability = ["data.management.storage", "data.management.transfer"]

            for gridhttps_host in gridhttps_host_list:

                if configuration['STORM_GRIDHTTPS_HTTP_ENABLED'].lower() == "true" and configuration['STORM_INFO_HTTP_SUPPORT'].lower() == "true":

                    # Glue2StorageEndpoint anonymous webdav
                    GLUE2EndpointInterfaceName = "http"
                    GLUE2EndpointID = GLUE2ServiceID + "/ep/" + gridhttps_host + ":" + configuration["STORM_GRIDHTTPS_HTTP_PORT"] + "/" + GLUE2EndpointInterfaceName + "/" + GLUE2EndpointInterfaceVersion
                    GLUE2EndpointURL = "http://" + gridhttps_host + ":" + configuration["STORM_GRIDHTTPS_HTTP_PORT"] + "/webdav/"
                    (dn, entry) = self.get_GLUE2StorageEndpoint(GLUE2EndpointID, GLUE2ServiceID, GLUE2EndpointURL, GLUE2EntityOtherInfo, GLUE2EndpointTechnology, GLUE2EndpointInterfaceName, 
                        GLUE2EndpointInterfaceVersion, GLUE2EndpointQualityLevel, GLUE2EndpointServingState, GLUE2EndpointCapability)
                    ldif_writer.unparse(dn, entry)

                    # Glue2AccessPolicy for the endpoint
                    GLUE2PolicyID = GLUE2EndpointID + "/ap/basic"
                    GLUE2AccessPolicyRule = ["'ALL'"]
                    (dn, entry) = self.get_GLUE2AccessPolicy(GLUE2PolicyID, GLUE2EndpointID, GLUE2ServiceID, GLUE2AccessPolicyRule)
                    ldif_writer.unparse(dn, entry)

                if configuration['STORM_INFO_HTTPS_SUPPORT'].lower() == "true":

                    # Glue2StorageEndpoint secure webdav
                    GLUE2EndpointInterfaceName = "https"
                    GLUE2EndpointID = GLUE2ServiceID + "/ep/" + gridhttps_host + ":" + configuration["STORM_GRIDHTTPS_HTTPS_PORT"] + "/" + GLUE2EndpointInterfaceName + "/" + GLUE2EndpointInterfaceVersion
                    GLUE2EndpointURL = "https://" + gridhttps_host + ":" + configuration["STORM_GRIDHTTPS_HTTPS_PORT"] + "/webdav/"
                    (dn, entry) = self.get_GLUE2StorageEndpoint(GLUE2EndpointID, GLUE2ServiceID, GLUE2EndpointURL, GLUE2EntityOtherInfo, GLUE2EndpointTechnology, GLUE2EndpointInterfaceName, 
                        GLUE2EndpointInterfaceVersion, GLUE2EndpointQualityLevel, GLUE2EndpointServingState, GLUE2EndpointCapability)
                    ldif_writer.unparse(dn, entry)

                    # Glue2AccessPolicy for the endpoint
                    GLUE2PolicyID = GLUE2EndpointID + "/ap/basic"
                    GLUE2PolicyRule = []
                    for vo in vos:
                        GLUE2PolicyRule.append("vo:" + vo)
                    (dn, entry) = self.get_GLUE2AccessPolicy(GLUE2PolicyID, GLUE2EndpointID, GLUE2ServiceID, GLUE2PolicyRule)
                    ldif_writer.unparse(dn, entry)

        f.close()
        # remove old backup files
        self.clear_old_backup_files()
        # create final file
        target_file = self.get_static_ldif_target_file(configuration)        
        logging.debug("Renaming '%s' to '%s' ...", target[1], target_file)
        shutil.copyfile(target[1], target_file)
        logging.debug("Deleting '%s' ...", target[1])
        os.remove(target[1])
        # set owner
        uid = pwd.getpwnam("ldap").pw_uid
        gid = grp.getgrnam("ldap").gr_gid
        os.chown(target_file, uid, gid)
        os.chmod(target_file, 0644)
        return target_file

    def get_enabled_protocols(self, configuration):
        enabled = {}
        if configuration["STORM_INFO_FILE_SUPPORT"].lower() == "true":
            enabled["file"] = self.access_protocols_versions["file"]
        if configuration["STORM_INFO_RFIO_SUPPORT"].lower() == "true":
            enabled["rfio"] = self.access_protocols_versions["rfio"]
        if configuration["STORM_INFO_GRIDFTP_SUPPORT"].lower() == "true":
            enabled["gsiftp"] = self.access_protocols_versions["gsiftp"]
        if configuration["STORM_INFO_ROOT_SUPPORT"].lower() == "true":
            enabled["root"] = self.access_protocols_versions["root"]
        if configuration["STORM_INFO_HTTP_SUPPORT"].lower() == "true":
            enabled["http"] = self.access_protocols_versions["http"]
        if configuration["STORM_INFO_HTTPS_SUPPORT"].lower() == "true":
            enabled["https"] = self.access_protocols_versions["https"]
        return enabled

    def get_vos(self, sas):
        vos = Set()
        for sa_name in sas:
            if ".*" not in sas[sa_name]["voname"]:
                vos.add(sas[sa_name]["voname"])
        return vos

    def clear_old_backup_files(self):
        # list GLUE2_STATIC_LDIF_FILE directory
        for f in os.listdir(os.path.dirname(self.GLUE2_STATIC_LDIF_FILE)):
            if re.search(r'static-file-glue2-storm\.ldif\.bkp_.*',f):
                os.remove(os.path.join(os.path.dirname(self.GLUE2_STATIC_LDIF_FILE), f))
                logging.debug("Removed %s", f)

    def get_static_ldif_target_file(self, configuration):
        if not os.path.isfile(self.GLUE2_STATIC_LDIF_FILE):
            return self.GLUE2_STATIC_LDIF_FILE
        logging.info("File '%s' already exists", self.GLUE2_STATIC_LDIF_FILE)
        if configuration["STORM_INFO_OVERWRITE"].lower() == "true":
            backup_file = self.GLUE2_STATIC_LDIF_FILE + ".bkp_" + time.strftime('%Y%m%d_%H%M%S')
            os.rename(self.GLUE2_STATIC_LDIF_FILE, backup_file)
            logging.info("Backup old configuration file in '%s'", backup_file)
            return self.GLUE2_STATIC_LDIF_FILE
        logging.warn("Can't overwrite old configuration file '%s'", self.GLUE2_STATIC_LDIF_FILE)
        return self.GLUE2_STATIC_LDIF_FILE + ".yaimnew_" + timestamp

    def remove_old_cron_file_if_exists(self):
        cFile = "/etc/cron.d/glite-info-glue2-dynamic-storm"
        if os.path.isfile(cFile):
            os.remove(cFile)
        return

    def get_service_configuration(self, configuration, vos):
        GLITE_INFO_SERVICE_VERSION = "2.2.0"
        GLITE_INFO_SERVICE_ENDPOINT = "httpg://" + configuration["STORM_FRONTEND_PUBLIC_HOST"] + ":" + configuration["STORM_FRONTEND_PORT"] + configuration["STORM_FRONTEND_PATH"]
        QUALITY_LEVEL = self.quality_levels[int(configuration['STORM_ENDPOINT_QUALITY_LEVEL'])]
        STATUS_CMD = INFO_SERVICE_SCRIPT + "/glite-info-service-test SRM_V2 && /usr/libexec/storm-dynamic-info-provider/storm-info-provider status"
        OWNER = "echo " + "; echo ".join(vos)
        ACBR = "echo VO:" + "; echo VO:".join(vos)
        content = {
            "init": "/usr/libexec/storm-dynamic-info-provider/storm-info-provider init-env --version " + GLITE_INFO_SERVICE_VERSION + " --endpoint " + GLITE_INFO_SERVICE_ENDPOINT,
            "service_type": "SRM",
            "get_version": "echo \"" + GLITE_INFO_SERVICE_VERSION + "\"",
            "get_endpoint": "echo \"" + GLITE_INFO_SERVICE_ENDPOINT + "\"",
            "WSDL_URL": "http://sdm.lbl.gov/srm-wg/srm.v2.2.wsdl",
            "semantics_URL": "http://sdm.lbl.gov/srm-wg/doc/SRM.v2.2.html",
            "get_starttime": "perl -e '@st=stat(\"/var/run/storm-backend-server.pid\");print \"@st[10]\\n\";'",
            "get_capabilities": "echo \"" + configuration['STORM_ENDPOINT_CAPABILITY'] + "\"",
            "get_implementor": "echo \"emi\"",
            "get_implementationname": "echo \"StoRM\"",
            "get_implementationversion": "rpm -qa | grep storm-backend-server | cut -d- -f4",
            "get_qualitylevel": "echo \"" + QUALITY_LEVEL + "\"",
            "get_servingstate": "echo 4",
            "get_data": "echo",
            "get_services": "echo",
            "get_status": STATUS_CMD,
            "get_owner": OWNER,
            "get_acbr": ACBR
        }
        return content

    def get_GLUE2StorageManager(self, GLUE2ManagerID, GLUE2ServiceID):
        dn = "GLUE2ManagerID=" + GLUE2ManagerID + ",GLUE2ServiceID=" + GLUE2ServiceID + "," + self.baseDN
        entry = { 
            'objectClass': ['GLUE2Manager', 'GLUE2StorageManager'],
            'GLUE2EntityCreationTime': [self.creation_time],
            'GLUE2ManagerID': [GLUE2ManagerID],
            'GLUE2ManagerProductName': ['StoRM'],
            'GLUE2ManagerProductVersion': ["`rpm -q --queryformat='%{VERSION}' storm-backend-server`"],
            'GLUE2StorageManagerStorageServiceForeignKey': [GLUE2ServiceID],
            'GLUE2ManagerServiceForeignKey': [GLUE2ServiceID]
        }
        return (dn, entry)

    def get_GLUE2DataStore(self, GLUE2ResourceID, GLUE2ManagerID, GLUE2ServiceID, GLUE2DataStoreType, GLUE2DataStoreLatency, 
        GLUE2DataStoreTotalSize):
        dn = "GLUE2ResourceID=" + GLUE2ResourceID + ",GLUE2ManagerID=" + GLUE2ManagerID + ",GLUE2ServiceID=" + GLUE2ServiceID + "," + self.baseDN
        entry = { 
            'objectClass': ['GLUE2DataStore', 'GLUE2Resource'],
            'GLUE2ResourceID': [GLUE2ResourceID],
            'GLUE2EntityCreationTime': [self.creation_time],
            'GLUE2DataStoreType': [GLUE2DataStoreType],
            'GLUE2DataStoreLatency': [GLUE2DataStoreLatency],
            'GLUE2DataStoreTotalSize': [str(GLUE2DataStoreTotalSize)],
            'GLUE2ResourceManagerForeignKey': [GLUE2ManagerID],
            'GLUE2DataStoreStorageManagerForeignKey': [GLUE2ManagerID]
        }
        return (dn, entry)

    def get_GLUE2StorageService(self, GLUE2ServiceID, GLUE2AdminDomainID, GLUE2ServiceQualityLevel):
        dn = "GLUE2ServiceID=" + GLUE2ServiceID + "," + self.baseDN
        entry = { 
            'objectClass': ['GLUE2Service', 'GLUE2StorageService'],
            'GLUE2EntityCreationTime': [self.creation_time],
            'GLUE2ServiceID': [GLUE2ServiceID],
            'GLUE2ServiceType': ['storm'],
            'GLUE2ServiceQualityLevel': [GLUE2ServiceQualityLevel],
            'GLUE2ServiceCapability': ['data.management.storage', 'data.management.transfer'],
            'GLUE2EntityOtherInfo': ['ProfileName=EGI', 'ProfileVersion=1.0'],
            'GLUE2ServiceAdminDomainForeignKey': [GLUE2AdminDomainID]
        }
        return (dn, entry)

    def get_GLUE2StorageAccessProtocol(self, GLUE2StorageAccessProtocolID, GLUE2ServiceID, GLUE2StorageAccessProtocolType, 
        GLUE2StorageAccessProtocolVersion):
        dn = "GLUE2StorageAccessProtocolID=" + GLUE2StorageAccessProtocolID + ",GLUE2ServiceID=" + GLUE2ServiceID + "," + self.baseDN
        entry = { 
            'objectClass': ['GLUE2StorageAccessProtocol'],
            'GLUE2StorageAccessProtocolID': [GLUE2StorageAccessProtocolID],
            'GLUE2EntityCreationTime': [self.creation_time],
            'GLUE2StorageAccessProtocolType': [GLUE2StorageAccessProtocolType],
            'GLUE2StorageAccessProtocolVersion': [GLUE2StorageAccessProtocolVersion],
            'GLUE2StorageAccessProtocolStorageServiceForeignKey': [GLUE2ServiceID]
        }
        return (dn, entry)

    def get_GLUE2StorageServiceCapacity(self, GLUE2StorageServiceCapacityID, GLUE2ServiceID, GLUE2StorageServiceCapacityType, 
        GLUE2StorageServiceCapacityTotalSize, GLUE2StorageServiceCapacityFreeSize, GLUE2StorageServiceCapacityUsedSize,
        GLUE2StorageServiceCapacityReservedSize):
        dn = "GLUE2StorageServiceCapacityID=" + GLUE2StorageServiceCapacityID + ",GLUE2ServiceID=" + GLUE2ServiceID + "," + self.baseDN
        entry = { 
            'objectClass': ['GLUE2StorageServiceCapacity'],
            'GLUE2EntityCreationTime': [self.creation_time],
            'GLUE2StorageServiceCapacityID': [GLUE2StorageServiceCapacityID],
            'GLUE2StorageServiceCapacityType': [GLUE2StorageServiceCapacityType],
            'GLUE2StorageServiceCapacityTotalSize': [str(GLUE2StorageServiceCapacityTotalSize)],
            'GLUE2StorageServiceCapacityFreeSize': [str(GLUE2StorageServiceCapacityFreeSize)],
            'GLUE2StorageServiceCapacityUsedSize': [str(GLUE2StorageServiceCapacityUsedSize)],
            'GLUE2StorageServiceCapacityReservedSize': [str(GLUE2StorageServiceCapacityReservedSize)],
            'GLUE2StorageServiceCapacityStorageServiceForeignKey': [GLUE2ServiceID]
        }
        return (dn, entry)

    def get_GLUE2StorageShare(self, GLUE2ShareID, GLUE2ServiceID, GLUE2StorageShareAccessLatency, GLUE2StorageShareRetentionPolicy,
        GLUE2StorageShareServingState, GLUE2StorageShareSharingID):
        dn = "GLUE2ShareID=" + GLUE2ShareID + ",GLUE2ServiceID=" + GLUE2ServiceID + "," + self.baseDN
        entry = { 
            'objectClass': ['GLUE2Share', 'GLUE2StorageShare'],
            'GLUE2ShareID': [GLUE2ShareID],
            'GLUE2EntityCreationTime': [self.creation_time],
            'GLUE2ShareServiceForeignKey': [GLUE2ServiceID],
            'GLUE2StorageShareAccessLatency': [GLUE2StorageShareAccessLatency],
            'GLUE2StorageShareRetentionPolicy': [GLUE2StorageShareRetentionPolicy],
            'GLUE2StorageShareServingState': [GLUE2StorageShareServingState],
            'GLUE2StorageShareSharingID': [GLUE2StorageShareSharingID],
            'GLUE2StorageShareExpirationMode': ['neverexpire'],
            'GLUE2StorageShareStorageServiceForeignKey': [GLUE2ServiceID]
        }
        return (dn, entry)

    def get_GLUE2StorageShareCapacity(self, GLUE2StorageShareCapacityID, GLUE2ShareID, GLUE2ServiceID, GLUE2StorageShareCapacityType,
        GLUE2StorageShareCapacityTotalSize, GLUE2StorageShareCapacityFreeSize, GLUE2StorageShareCapacityUsedSize, 
        GLUE2StorageShareCapacityReservedSize):
        dn = "GLUE2StorageShareCapacityID=" + GLUE2StorageShareCapacityID + ",GLUE2ShareID=" + GLUE2ShareID + ",GLUE2ServiceID=" + GLUE2ServiceID + "," + self.baseDN
        entry = { 
            'objectClass': ['GLUE2StorageShareCapacity'],
            'GLUE2EntityCreationTime': [self.creation_time],
            'GLUE2StorageShareCapacityID': [GLUE2StorageShareCapacityID],
            'GLUE2StorageShareCapacityType': [GLUE2StorageShareCapacityType],
            'GLUE2StorageShareCapacityTotalSize': [str(GLUE2StorageShareCapacityTotalSize)],
            'GLUE2StorageShareCapacityFreeSize': [str(GLUE2StorageShareCapacityFreeSize)],
            'GLUE2StorageShareCapacityUsedSize': [str(GLUE2StorageShareCapacityUsedSize)],
            'GLUE2StorageShareCapacityReservedSize': [str(GLUE2StorageShareCapacityReservedSize)],
            'GLUE2StorageShareCapacityStorageShareForeignKey': [GLUE2ShareID]
        }
        return (dn, entry)

    def get_GLUE2MappingPolicy(self, GLUE2PolicyID, GLUE2ShareID, GLUE2ServiceID, GLUE2UserDomainID, GLUE2PolicyRule):
        dn = "GLUE2PolicyID=" + GLUE2PolicyID + ",GLUE2ShareID=" + GLUE2ShareID + ",GLUE2ServiceID=" + GLUE2ServiceID + "," + self.baseDN
        entry = { 
            'objectClass': ['GLUE2Policy', 'GLUE2MappingPolicy'],
            'GLUE2PolicyID': [GLUE2PolicyID],
            'GLUE2EntityCreationTime': [self.creation_time],
            'GLUE2PolicyScheme': ['basic'],
            'GLUE2PolicyRule': GLUE2PolicyRule,
            'GLUE2MappingPolicyShareForeignKey': [GLUE2ShareID],
            'GLUE2PolicyUserDomainForeignKey': [GLUE2UserDomainID]
        }
        return (dn, entry)

    def get_GLUE2StorageEndpoint(self, GLUE2EndpointID, GLUE2ServiceID, GLUE2EndpointURL, GLUE2EntityOtherInfo, 
        GLUE2EndpointTechnology, GLUE2EndpointInterfaceName, GLUE2EndpointInterfaceVersion, GLUE2EndpointQualityLevel,
        GLUE2EndpointServingState, GLUE2EndpointCapability):
        dn = "GLUE2EndpointID=" + GLUE2EndpointID + ",GLUE2ServiceID=" + GLUE2ServiceID + "," + self.baseDN
        entry = {
            'objectClass': ['GLUE2Endpoint', 'GLUE2StorageEndpoint'],
            'GLUE2EntityCreationTime': [self.creation_time],
            'GLUE2EntityOtherInfo': GLUE2EntityOtherInfo,
            'GLUE2EndpointID': [GLUE2EndpointID],
            'GLUE2EndpointURL': [GLUE2EndpointURL],
            'GLUE2EndpointTechnology': [GLUE2EndpointTechnology],
            'GLUE2EndpointInterfaceName': [GLUE2EndpointInterfaceName],
            'GLUE2EndpointInterfaceVersion': [GLUE2EndpointInterfaceVersion],
            'GLUE2EndpointImplementationName': ['StoRM'],
            'GLUE2EndpointImplementationVersion': ["`rpm -q --queryformat='%{VERSION}' storm-backend-server`"],
            'GLUE2EndpointQualityLevel': [GLUE2EndpointQualityLevel],
            'GLUE2EndpointHealthState': ['ok'],
            'GLUE2EndpointServingState': [GLUE2EndpointServingState],
            'GLUE2EndpointIssuerCA': ["`openssl x509 -issuer -noout -in /etc/grid-security/hostcert.pem | sed 's/^[^/]*//'`"],
            'GLUE2EndpointCapability': GLUE2EndpointCapability,
            'GLUE2EndpointServiceForeignKey': [GLUE2ServiceID]
        }
        return (dn, entry)

    def get_GLUE2AccessPolicy(self, GLUE2PolicyID, GLUE2EndpointID, GLUE2ServiceID, GLUE2PolicyRule):
        dn = "GLUE2PolicyID=" + GLUE2PolicyID + ",GLUE2EndpointID=" + GLUE2EndpointID + ",GLUE2ServiceID=" + GLUE2ServiceID + "," + self.baseDN
        entry = { 
            'objectClass': ['GLUE2Policy', 'GLUE2AccessPolicy'],
            'GLUE2PolicyID': [GLUE2PolicyID],
            'GLUE2EntityCreationTime': [self.creation_time],
            'GLUE2PolicyScheme': ['basic'],
            'GLUE2PolicyRule': GLUE2PolicyRule,
            'GLUE2AccessPolicyEndpointForeignKey': [GLUE2EndpointID]
        }
        return (dn, entry)
