from uptime_kuma_api.api import UptimeKumaApi, MonitorType
from helpers import *
import os

logPrefix = "[mod-auto-uptime-kuma]"


class SwagUptimeKuma:
    swagTagName = "swag"
    swagUptimeKumaConfigDir = "/auto-uptime-kuma"

    _api = None
    _apiSwagTag = None
    apiMonitors = None

    defaultMonitorConfig = dict(
        type=MonitorType.HTTP,
        description="Automatically generated by SWAG auto-uptime-kuma"
    )

    def __init__(self, url, username, password):
        self._api = UptimeKumaApi(url)
        self._api.login(username, password)
        self.apiMonitors = self._api.get_monitors()

        if not os.path.exists(self.swagUptimeKumaConfigDir):
            print(
                f"{logPrefix} Creating config directory '{self.swagUptimeKumaConfigDir}'")
            os.makedirs(self.swagUptimeKumaConfigDir)

    def disconnect(self):
        """
        API has to be disconnected at the end as the connection is blocking
        """
        self._api.disconnect()

    def getSwagTag(self):
        """
        The "swag" tag is used to detect in API which monitors were created using this script.
        """
        # If the tag was not fetched yet
        if (self._apiSwagTag == None):
            for tag in self._api.get_tags():
                if (tag['name'] == self.swagTagName):
                    self._apiSwagTag = tag
                    break

        # If the tag was not in API then it has to be created
        if (self._apiSwagTag == None):
            self._apiSwagTag = self._api.add_tag(
                name=self.swagTagName, color="#ff4f97")

        return self._apiSwagTag

    def parseMonitorData(self, containerName, domainName, monitorData):
        """
        Some of the container label values might have to be converted before sending to API.
        Additionally merge default config with label config.
        """
        # Convert strings that are lists in API
        for key in ["accepted_statuscodes", "notificationIDList"]:
            if (key in monitorData and type(monitorData[key]) is str):
                monitorData[key] = monitorData[key].split(",")

        dynamicMonitorConfig = {
            "name": containerName.title(),
            "url": f"https://{containerName}.{domainName}"
        }

        return merge_dicts(self.defaultMonitorConfig, dynamicMonitorConfig, monitorData)

    def addMonitor(self, containerName, domainName, monitorData):
        monitorData = self.parseMonitorData(
            containerName, domainName, monitorData)
        if (has_key_with_value(self.apiMonitors, "name", monitorData['name'])):
            print(
                f"{logPrefix} Uptime Kuma already contains '{monitorData['name']}' monitor, skipping...")
            return

        print(
            f"{logPrefix} Adding monitor '{monitorData['name']}'")

        monitor = self._api.add_monitor(**monitorData)

        self._api.add_monitor_tag(
            tag_id=self.getSwagTag()['id'],
            monitor_id=monitor['monitorID'],
            value=containerName
        )

        content = self.buildContainerConfigContent(monitorData)
        write_file(
            f"{self.swagUptimeKumaConfigDir}/{containerName}.conf", content)

    def deleteMonitor(self, containerName):
        monitorData = self.getMonitor(containerName)
        print(
            f"{logPrefix} Deleting monitor {monitorData['id']}:{monitorData['name']}")
        self._api.delete_monitor(monitorData['id'])

    def deleteMonitors(self, containerNames):
        print(f"{logPrefix} Deleting all monitors that had their containers removed")
        if (containerNames):
            for containerName in containerNames:
                self.deleteMonitor(containerName)
        else:
            print(f"{logPrefix} Nothing to remove")

    def updateMonitor(self, containerName, domainName, monitorData):
        """
        Please not that due to API limitations the "update" action is actually "delete" followed by "add"
        so that in the end the monitors are actually recreated
        """
        newContent = self.buildContainerConfigContent(monitorData)
        oldContent = self.readContainerConfigContent(containerName)
        existingMonitorData = self.getMonitor(containerName)

        if (not oldContent == newContent):
            print(
                f"{logPrefix} Updating (Delete and Add) monitor {existingMonitorData['id']}:{existingMonitorData['name']}")
            self.deleteMonitor(containerName)
            self.addMonitor(containerName, domainName, monitorData)
        else:
            print(
                f"{logPrefix} Monitor {existingMonitorData['id']}:{existingMonitorData['name']} is unchanged, skipping...")

    def buildContainerConfigContent(self, monitorData):
        """
        In order to compare if container labels were changed the contents are stored in config files for each container.
        """
        content = ""
        for key, value in monitorData.items():
            content += f'{key}={value}\n'
        return content.strip()

    def readContainerConfigContent(self, containerName):
        fileName = f"{self.swagUptimeKumaConfigDir}/{containerName}.conf"
        if (not os.path.exists(fileName)):
            return ""

        return read_file(fileName).strip()

    def getMonitor(self, containerName):
        for monitor in self.apiMonitors:
            swagTagValue = self.getMonitorSwagTagValue(monitor)
            if (swagTagValue != None and swagTagValue == containerName):
                return monitor
        return None

    def monitorExists(self, containerName):
        return True if self.getMonitor(containerName) else False

    def getMonitorSwagTagValue(self, monitorData):
        """
        This value is container name itself. Used to link containers with monitors
        """
        for tag in monitorData.get('tags'):
            if (has_key_with_value(tag, "name", self.swagTagName)):
                return tag['value']
        return None

    def purgeData(self):
        """
        Removes all of the monitors and files created with this script
        """
        print(f"{logPrefix} Purging all monitors added by swag")

        for monitor in self.apiMonitors:
            containerName = self.getMonitorSwagTagValue(monitor)
            if (containerName != None):
                self.deleteMonitor(containerName)

        if os.path.exists(self.swagUptimeKumaConfigDir):
            print(
                f"{logPrefix} Purging config directory '{self.swagUptimeKumaConfigDir}'")
            file_list = os.listdir(self.swagUptimeKumaConfigDir)

            for filename in file_list:
                file_path = os.path.join(
                    self.swagUptimeKumaConfigDir, filename)
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    print(f"{logPrefix} Removed '{file_path}' file")

        print(f"{logPrefix} Purging finished")
