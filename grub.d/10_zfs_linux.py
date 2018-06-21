#!/usr/bin/env python3.6

import sys

import os
import platform
import pyzfscmds.system.agnostic
import pyzfscmds.utility
import re
import subprocess
import zedenv.lib.be
from typing import List, Optional


def source(file: str):
    """
    'sources' a file and manipulates environment variables
    """

    env_command = ['sh', '-c', f'set -a && . {file} && env']

    try:
        env_output = subprocess.check_output(
            env_command, universal_newlines=True, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to gsource{file}.\n{e}\n.")

    for line in env_output.splitlines():
        (key, _, value) = line.partition("=")
        os.environ[key] = value


def normalize_string(str_input: str):
    """
    Given a string, remove all non alphanumerics, and replace spaces with underscores
    """
    str_list = []
    for c in str_input.split(" "):
        san = [l.lower() for l in c if l.isalnum()]
        str_list.append("".join(san))

    return "_".join(str_list)


def grub_command(command: str, call_args: List[str] = None):
    cmd_call = [command]
    if call_args:
        cmd_call.extend(call_args)

    try:
        cmd_output = subprocess.check_output(
            cmd_call, universal_newlines=True, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to run {command}.\n{e}\n.")

    return cmd_output.splitlines()


class GrubLinuxEntry:

    def __init__(self, linux: str,
                 grub_os: str,
                 be_root: str,
                 rpool: str,
                 genkernel_arch: str,
                 boot_environment_kernels: dict,
                 grub_cmdline_linux: str,
                 grub_cmdline_linux_default: str):

        self.grub_cmdline_linux = grub_cmdline_linux
        self.grub_cmdline_linux_default = grub_cmdline_linux_default

        self.linux = linux
        self.grub_os = grub_os
        self.genkernel_arch = genkernel_arch

        self.basename = os.path.basename(linux)
        self.dirname = os.path.dirname(linux)

        self.boot_environment_kernels = boot_environment_kernels

        try:
            self.rel_dirname = grub_command("grub-mkrelpath", [self.dirname])[0]
        except RuntimeError as e:
            sys.exit(e)
        self.version = self.get_linux_version()

        self.rpool = rpool
        self.be_root = be_root
        self.boot_environment = self.get_boot_environment()

        # Root dataset will double as device ID
        self.linux_root_dataset = os.path.join(
            f"{self.be_root}", self.boot_environment)
        self.linux_root_device = f"ZFS={self.linux_root_dataset}"
        self.boot_device_id = self.linux_root_dataset

        self.initrd_early = self.get_initrd_early()
        self.initrd_real = self.get_initrd_real()

        self.kernel_config = self.get_kernel_config()

        self.initramfs = self.get_from_config(r'CONFIG_INITRAMFS_SOURCE=(.*)$')

        self.grub_default_entry = None
        if "GRUB_ACTUAL_DEFAULT" in os.environ:
            self.grub_default_entry = os.environ['GRUB_ACTUAL_DEFAULT']

        self.grub_save_default = None
        if "GRUB_SAVEDEFAULT" in os.environ:
            self.grub_save_default = True if os.environ['GRUB_SAVEDEFAULT'] == "true" else False

        self.grub_gfxpayload_linux = None
        if "GRUB_GFXPAYLOAD_LINUX" in os.environ:
            self.grub_gfxpayload_linux = os.environ['GRUB_GFXPAYLOAD_LINUX']

        self.grub_entries = []

    @staticmethod
    def entry_line(entry_line: str, submenu_indent: int = 0):
        return ("\t" * submenu_indent) + entry_line

    def generate_entry(self, grub_class, grub_args, entry_type,
                       entry_indentation: int = 0) -> List[str]:

        entry = []

        if entry_type != "simple":
            if entry_type == "recovery":
                title = f"{self.grub_os} with Linux {self.version} (recovery mode)"
            else:
                title = f"{self.grub_os} with Linux {self.version}"

            # TODO: If matches default...

            entry.append(
                self.entry_line(
                    f"menuentry '{title}' {grub_class} $menuentry_id_option "
                    f"'gnulinux-{self.version}-{entry_type}-{self.boot_device_id}' {{",
                    submenu_indent=entry_indentation))
        else:
            entry.append(self.entry_line(
                f"menuentry '{self.grub_os}' {grub_class} $menuentry_id_option "
                f"'gnulinux-simple-{self.boot_device_id}' {{", submenu_indent=entry_indentation))

        # Graphics section
        entry.append(self.entry_line("load_video", submenu_indent=entry_indentation + 1))
        if not self.grub_gfxpayload_linux:
            fb_efi = self.get_from_config(r'(CONFIG_FB_EFI=y)')
            vt_hw_console_binding = self.get_from_config(r'(CONFIG_VT_HW_CONSOLE_BINDING=y)')

            if fb_efi and vt_hw_console_binding:
                entry.append(
                    self.entry_line('set gfxpayload=keep', submenu_indent=entry_indentation + 1))
        else:
            entry.append(self.entry_line(f"set gfxpayload={self.grub_gfxpayload_linux}",
                                         submenu_indent=entry_indentation + 1))

            entry.append(self.entry_line(f"insmod gzio", submenu_indent=entry_indentation + 1))

        # TODO: prepare_grub_to_access_device section

        entry.append(self.entry_line(f"echo 'Loading Linux {self.version} ...'",
                                     submenu_indent=entry_indentation + 1))
        rel_linux = os.path.join(self.rel_dirname, self.basename)
        entry.append(
            self.entry_line(f"linux {rel_linux} root={self.linux_root_device} ro {grub_args}",
                            submenu_indent=entry_indentation + 1))

        initrd = self.get_initrd()

        if initrd:
            entry.append(self.entry_line(f"echo 'Loading initial ramdisk ...'",
                                         submenu_indent=entry_indentation + 1))
            entry.append(self.entry_line(f"initrd {' '.join(initrd)}",
                                         submenu_indent=entry_indentation + 1))

        entry.append(self.entry_line("}", entry_indentation))

        return entry

    def get_from_config(self, pattern) -> Optional[str]:
        """
        Check kernel_config for initramfs setting
        """
        config_match = None
        if self.kernel_config:
            reg = re.compile(pattern)

            with open(self.kernel_config) as f:
                config = f.read().splitlines()

            config_match = next((reg.match(l).group(1) for l in config if reg.match(l)), None)

        return config_match

    def get_kernel_config(self) -> Optional[str]:
        configs = [f"{self.dirname}/config-{self.version}",
                   f"/etc/kernels/kernel-config-{self.version}"]
        return next((c for c in configs if os.path.isfile(c)), None)

    def get_initrd(self) -> list:
        initrd = []
        if self.initrd_real:
            initrd.append(os.path.join(self.rel_dirname, self.initrd_real))

        if self.initrd_early:
            initrd.extend([os.path.join(self.rel_dirname, ie) for ie in self.initrd_early])

        return initrd

    def get_initrd_early(self) -> list:
        """
        Get microcode images
        https://www.mail-archive.com/grub-devel@gnu.org/msg26775.html
        See grub-mkconfig for code
        GRUB_EARLY_INITRD_LINUX_STOCK is distro provided microcode, ie:
          intel-uc.img intel-ucode.img amd-uc.img amd-ucode.img
          early_ucode.cpio microcode.cpio"
        GRUB_EARLY_INITRD_LINUX_CUSTOM is for your custom created images
        """
        early_initrd = []
        if "GRUB_EARLY_INITRD_LINUX_STOCK" in os.environ:
            early_initrd.extend(os.environ['GRUB_EARLY_INITRD_LINUX_STOCK'].split())

        if "GRUB_EARLY_INITRD_LINUX_CUSTOM" in os.environ:
            early_initrd.extend(os.environ['GRUB_EARLY_INITRD_LINUX_CUSTOM'].split())

        return [i for i in early_initrd if os.path.isfile(os.path.join(self.dirname, i))]

    def get_initrd_real(self) -> Optional[str]:
        initrd_list = [f"initrd.img-{self.version}",
                       f"initrd-{self.version}.img",
                       f"initrd-{self.version}.gz",
                       f"initrd-{self.version}",
                       f"initramfs-{self.version}.img",
                       f"initramfs-genkernel-{self.version}"
                       f"initramfs-genkernel-{self.genkernel_arch}-{self.version}"]

        initrd_real = next(
            (i for i in initrd_list if os.path.isfile(os.path.join(self.dirname, i))), None)

        # if initrd_real:
        #     return initrd_real[0]

        return initrd_real

    def get_boot_environment(self):
        """
        Get name of BE from kernel directory
        """
        target = re.search(r'zedenv-(.*)/*$', self.dirname)
        if target:
            return target.group(1)
        return None

    def get_linux_version(self):
        """
        Gets the version after kernel, if there is one
        Example:
             vmlinuz-4.16.12_1 gives 4.16.12_1
        """

        target = re.search(r'^[^0-9\-]*-(.*)$', self.basename)
        if target:
            return target.group(1)
        return ""


class Generator:

    def __init__(self):

        self.prefix = "/usr"
        self.exec_prefix = "/usr"
        self.data_root_dir = "/usr/share"

        if "pkgdatadir" in os.environ:
            self.pkgdatadir = os.environ['pkgdatadir']
        else:
            self.pkgdatadir = "/usr/share/grub"

        self.text_domain = "grub"
        self.text_domain_dir = f"{self.data_root_dir}/locale"

        self.entry_type = "advanced"

        # Update environment variables by sourcing grub defaults
        source("/etc/default/grub")

        grub_class = "--class gnu-linux --class gnu --class os"

        if "GRUB_DISTRIBUTOR" in os.environ:
            grub_distributor = os.environ['GRUB_DISTRIBUTOR']
            self.grub_os = f"{grub_distributor} GNU/Linux"
            self.grub_class = f"--class {normalize_string(grub_distributor)} {grub_class}"
        else:
            self.grub_os = "GNU/Linux"
            self.grub_class = grub_class

        # Default to true in order to maintain compatibility with older kernels.
        self.grub_disable_linux_partuuid = True
        if "GRUB_DISABLE_LINUX_PARTUUID" in os.environ:
            if os.environ['GRUB_DISABLE_LINUX_PARTUUID'] == ("false" or "False" or "0"):
                self.grub_disable_linux_partuuid = False

        if "GRUB_CMDLINE_LINUX" in os.environ:
            self.grub_cmdline_linux = os.environ['GRUB_CMDLINE_LINUX']
        else:
            self.grub_cmdline_linux = ""

        if "GRUB_CMDLINE_LINUX_DEFAULT" in os.environ:
            self.grub_cmdline_linux_default = os.environ['GRUB_CMDLINE_LINUX_DEFAULT']
        else:
            self.grub_cmdline_linux_default = ""

        if "GRUB_DISABLE_SUBMENU" in os.environ and os.environ['GRUB_DISABLE_SUBMENU'] == "y":
            self.grub_disable_submenu = True
        else:
            self.grub_disable_submenu = False

        self.grub_disable_recovery = None
        if "GRUB_DISABLE_RECOVERY" in os.environ:
            if os.environ['GRUB_DISABLE_RECOVERY'] == "true":
                self.grub_disable_recovery = True
            else:
                self.grub_disable_recovery = False

        self.root_dataset = pyzfscmds.system.agnostic.mountpoint_dataset("/")
        self.be_root = zedenv.lib.be.root()

        # in GRUB terms, bootfs is everything after pool
        self.bootfs = "/" + self.root_dataset.split("/", 1)[1]
        self.rpool = self.root_dataset.split("/")[0]
        self.linux_root_device = f"ZFS={self.rpool}{self.bootfs}"

        self.machine = platform.machine()

        self.invalid_filenames = ["readme"]  # Normalized to lowercase
        self.invalid_extensions = [".dpkg", ".rpmsave", ".rpmnew", ".pacsave", ".pacnew"]

        self.genkernel_arch = self.get_genkernel_arch()

        self.linux_entries = []

        self.grub_boot = zedenv.lib.be.get_property(self.root_dataset, 'org.zedenv.grub:boot')
        if not self.grub_boot or self.grub_boot == "-":
            self.grub_boot = "/mnt/boot"

        grub_boot_on_zfs = zedenv.lib.be.get_property(
            self.root_dataset, 'org.zedenv.grub:bootonzfs')
        if grub_boot_on_zfs.lower() == ("1" or "yes"):
            self.grub_boot_on_zfs = True
            self.boot_env_kernels = os.path.join(self.grub_boot, "zfsenv")
        else:
            self.grub_boot_on_zfs = False
            self.boot_env_kernels = os.path.join(self.grub_boot, "env")

        self.boot_list = self.get_boot_environments_boot_list()

    def file_valid(self, file_path):
        """
        Run equivalent checks to grub_file_is_not_garbage() from grub-mkconfig_lib
        Check file is valid and not one of:
        *.dpkg - debian dpkg
        *.rpmsave | *.rpmnew
        README* | */README* - documentation
        """
        if not os.path.isfile(file_path):
            return False

        file = os.path.basename(file_path)
        _, ext = os.path.splitext(file)

        if ext in self.invalid_extensions:
            return False

        if next((True for f in self.invalid_filenames if f.lower() in file.lower()), False):
            return False

        return True

    def get_boot_environments_boot_list(self) -> List[Optional[dict]]:
        """
        Get a list of dicts containing all BE kernels
        :return:
        """

        vmlinuz = r'(vmlinuz-.*)'
        vmlinux = r'(vmlinux-.*)'
        kernel = r'(kernel-.*)'

        boot_search = f"{vmlinuz}|{kernel}"

        if re.search(r'(i[36]86)|x86_64', self.machine):
            boot_regex = re.compile(boot_search)
        else:
            boot_search = f"{boot_search}|{vmlinux}"
            boot_regex = re.compile(boot_search)

        boot_entries = []
        for e in os.listdir(self.boot_env_kernels):
            boot_dir = os.path.join(self.boot_env_kernels, e)

            boot_files = os.listdir(boot_dir)
            kernel_matches = [i for i in boot_files
                              if boot_regex.match(i) and self.file_valid(
                                                                os.path.join(boot_dir, i))]

            boot_entries.append({
                "directory": boot_dir,
                "files": boot_files,
                "kernels": kernel_matches
            })

        return boot_entries

    def get_regular_grub_boot_list(self, boot_path: str = "/boot"):
        """
        Check if grub list item shows up

        machine=`uname -m`
        case "x$machine" in
            xi?86 | xx86_64)
            list=
            for i in /boot/vmlinuz-* /vmlinuz-* /boot/kernel-* ; do
                if grub_file_is_not_garbage "$i" ; then list="$list $i" ; fi
            done ;;
            *)
            list=
            for i in /boot/vmlinuz-* /boot/vmlinux-* /vmlinuz-* /vmlinux-* /boot/kernel-* ; do
                          if grub_file_is_not_garbage "$i" ; then list="$list $i" ; fi
            done ;;
        esac
        """

        boot_list = []

        vmlinuz = r'(/vmlinuz-.*)'
        vmlinux = r'(/vmlinux-.*)'
        kernel = r'(/kernel-.*)'

        boot_entries = [os.path.join(boot_path, e) for e in os.listdir(boot_path)]
        boot_entries.extend([os.path.join(boot_path, e) for e in os.listdir("/")])

        boot_search = f"{boot_path}{vmlinuz}|{boot_path}{kernel}|{vmlinuz}"

        if re.search(r'(i[36]86)|x86_64', self.machine):
            boot_regex = re.compile(boot_search)
        else:
            boot_search = f"{boot_search}|{boot_path}{vmlinux}|{vmlinux}"
            boot_regex = re.compile(boot_search)

        for i in boot_entries:
            if boot_regex.search(i) and self.file_valid(i):
                boot_list.append(i)

        return boot_list

    def get_genkernel_arch(self):

        if re.search(r'i[36]86', self.machine):
            return "x86"

        if re.search(r'mips|mips64', self.machine):
            return "mips"

        if re.search(r'mipsel|mips64el', self.machine):
            return "mipsel"

        if re.search(r'arm.*', self.machine):
            return "arm"

        return self.machine

    # grub_class, grub_args,
    # entry_indentation: int = 0) -> List[str]:
    def generate_grub_entries(self):
        indent = 0
        is_top_level = True

        entries = []

        for i in self.boot_list:
            for j in i['kernels']:
                grub_entry = GrubLinuxEntry(
                    os.path.join(i['directory'], j), self.grub_os, self.be_root, self.rpool,
                    self.genkernel_arch, i, self.grub_cmdline_linux,
                    self.grub_cmdline_linux_default)
                self.linux_entries.append(grub_entry)

                if is_top_level and not self.grub_disable_submenu:
                    # Simple entry
                    entries.append(
                        grub_entry.generate_entry(
                            self.grub_class,
                            f"{self.grub_cmdline_linux} {self.grub_cmdline_linux_default}",
                            "simple", entry_indentation=indent))

                    # Submenu title
                    entries.append(
                        [(f"submenu 'Advanced options for {self.grub_os}' $menuentry_id_option "
                          f"'gnulinux-advanced-{grub_entry.boot_device_id}' {{")])
                    is_top_level = False
                    indent = 1

                # Advanced entry
                entries.append(
                    grub_entry.generate_entry(
                        self.grub_class,
                        f"{self.grub_cmdline_linux} {self.grub_cmdline_linux_default}",
                        "advanced", entry_indentation=indent))

                # Recovery entry
                if self.grub_disable_recovery:
                    entries.append(
                        grub_entry.generate_entry(
                            self.grub_class,
                            f"single {self.grub_cmdline_linux}",
                            "recovery", entry_indentation=indent))

                if not is_top_level:
                    entries.append("}")

        return entries


grub = Generator()
for en in grub.generate_grub_entries():
    for l in en:
        print(l)
