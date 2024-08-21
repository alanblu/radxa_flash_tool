import argparse
import pexpect
import re
from dataclasses import dataclass
import logging
import os
import sys

@dataclass
class RadxaDevice:
    devno: int
    vid: str
    pid: str
    location_id: int


class ColoredFormatter(logging.Formatter):
    COLORS = {
        'ERROR': '\033[91m',  # Red
        'WARNING': '\033[93m',  # Yellow
        'INFO': '\033[0m',  # Green
        'DEBUG': '\033[94m'  # Blue
    }

    RESET = '\033[0m'

    def format(self, record):
        log_color = self.COLORS.get(record.levelname, '')
        log_message = super().format(record)
        return f"{log_color}[{record.levelname}] {log_message}{self.RESET}"



class UpgradeTool:
    
    def __init__(self, ul_file, im_file, command="sudo ./upgrade_tool"):
        logging.basicConfig(
            level=logging.INFO,
            format='%(levelname)s: %(message)s',
            handlers=[logging.StreamHandler()]
        )

        logging.getLogger().handlers[0].setFormatter(ColoredFormatter())

        if os.path.exists(ul_file):
            self.ul_file = ul_file
        else:
            print("Upgrade loader file path does not exist.")
            exit(1)
        
        if os.path.exists(im_file):
            self.im_file = im_file
        else:
            print("Image file path does not exist.")
            exit(1)
        
        self.command = command
        self.child = None
        self.num_devices = 0
        self.devices = []

    def run(self):
        self.child = pexpect.spawn(self.command, timeout=None,  echo=True)

        try:
            self.initial_prompt()
            
            if not self.devices:
                logging.info("No Radxa devices found.")
                logging.info("If the device is connected try to set it in Maskrom mode https://wiki.radxa.com/Rock3/installusb-install-radxa-cm3-io.")
                return

            for device in self.devices:
                self.run_upgrade(device)
            
        except pexpect.exceptions.EOF:
            logging.error("An error occurred during the upgrade process.")

    def expect_initial_prompt(self):
        self.child.expect(["Rescan press <R>,Quit press <Q>:", pexpect.EOF])


    def initial_prompt(self):
        self.expect_initial_prompt()
        output = self.child.before.decode("utf-8")

        if "No found rockusb" in output: 
            logging.info("No Rescan prompt found.")
            return

        elif "Select input DevNo" in output:
            self.rescan_devices() # Send 'R' to rescan
            self.child.expect("Found (\d+) rockusb,Select input DevNo,Rescan press <R>,Quit press <Q>:")
            self.num_devices = int(self.child.match.group(1))

            # Parse the output to create a list of RadxaDevice instances using list comprehension
            device_lines = re.findall(r"DevNo\s*=\s*(\d+)\DVid=0x([0-9A-Fa-f]+),Pid=0x([0-9A-Fa-f]+),LocationID=(\d+)", output)
            
            self.devices = [
                RadxaDevice(int(devno), vid, pid, int(location_id))
                for devno, vid, pid, location_id in device_lines
            ]

    def rescan_devices(self):
        self.child.sendline("r")  # Send 'r' to rescan

    def run_upgrade(self, device):
        self.child.sendline(str(device.devno))
        self.child.expect("Rockusb>")
        self.send_upgrade_commands(device.location_id)

    def send_upgrade_commands(self, device_location):
        commands = [
            f"ul {self.ul_file} -noreset",
            f"wl 0 {self.im_file}",
        ]

        for command in commands:

            self.child.sendline(command)
            if command.startswith("ul"):
                self.upgrade_loader(device_location)

            if command.startswith("wl"):
                self.write_lba(device_location)
            


    def upgrade_loader(self, location):
        try:
            self.child.expect(["Rockusb>", pexpect.TIMEOUT], timeout=500)

            output = self.child.before.decode("utf-8")

            if "Upgrade loader ok" in output:
                logging.info(f"Upgrade loader for device in location {location} was successful.")
            
            elif "Download Boot Fail" in output:
                logging.error(f"Upgrade loader command for device in location {location} failed.")
                logging.info("If the device is connected try to set it in Maskrom mode https://wiki.radxa.com/Rock3/installusb-install-radxa-cm3-io.")
                # Add error handling logic here
            else:
                logging.error(f"Unknow error for device in location {location}.")
                
        
        except pexpect.TIMEOUT:
            logging.error("Upgrade loader command timed out.")
            # Add error handling logic here

    def write_lba(self, location):
        
        try:
            self.child.expect(["Rockusb>", pexpect.TIMEOUT], timeout=20)
            output = self.child.before.decode("utf-8")
            

            if "Write LBA failed!" in output:
                logging.error(f"Write LBA for device in location {location} failed")
                logging.info("If the device is connected try to set it in Maskrom mode https://wiki.radxa.com/Rock3/installusb-install-radxa-cm3-io.")
                # Add error handling logic here
            
            else:
                logging.info(f"Writing LBA for device in location {location}.")
                self.writing_lba()
                # Add error handling logic here
        
        except pexpect.TIMEOUT:
            logging.error("Upgrade loader command timed out.")
            # Add error handling logic here


    def writing_lba(self):
        last_percentage = -1  # Initialize with a value that won't match any percentage
        while True:
            index = self.child.expect([r"Write LBA from file \(\d+%\)", pexpect.EOF], timeout=None)

            if index == 0:
                progress_message = self.child.match.group(0).decode("utf-8")
                progress_percentage = int(re.search(r"\((\d+)%\)", progress_message).group(1))
                
                if progress_percentage != last_percentage:
                    last_percentage = progress_percentage
                    progress_bar = "[" + "=" * (progress_percentage // 2) + " " * ((100 - progress_percentage) // 2) + "]"
                    log_message = "\033[92mProgress: {:3d}% {}\033[0m".format(progress_percentage, progress_bar)
                    sys.stdout.write("\r" + log_message )
                    sys.stdout.flush()
                
                if progress_percentage == 100:
                    print("")
                    logging.info("Write process completed.")
                    break
                
        else:
            logging.info("Upgrade tool finished.")

        self.child.sendline("cd")
        self.expect_initial_prompt()


def main():

    parser = argparse.ArgumentParser(description="Upgrade Tool")
    parser.add_argument("-ul", dest="ul_file", default="./RTE_Files/rk356x_spl_loader_ddr1056_v1.10.111.bin", help="Path to ul file")
    parser.add_argument("-im", dest="im_file", default="./RTE_Files/lade-image-radxa-radxa-cm3-io-rk3566-20230505103716.gptimg", help="Path to im file")
    args = parser.parse_args()



    upgrade_tool = UpgradeTool(args.ul_file, args.im_file)
    upgrade_tool.run()

if __name__ == "__main__":
    main()
    