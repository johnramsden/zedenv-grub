==================
zedenv GRUB Plugin
==================

zedenv - ZFS boot environment manager - GRUB plugin

Install
-------

Install ``zedenv`` then ``zedenv-grub``.

Setup
-----

One of two types of setup needs to be used with grub.

* Boot on ZFS - separate ``grub`` dataset needed.
* Separate partition for kernels

Boot on ZFS (Recommended)
#########################

To use boot on ZFS:

* A ``grub`` dataset is needed. It should be mounted at ``/boot/grub``.
* ``org.zedenv.grub:bootonzfs`` should be set to ``yes``
* Individual boot environments should contain their kernels in ``/boot``, which should be part of the root dataset.

To convert an existing grub install, set up the ``grub`` dataset, and mount it. Then install grub again. 

.. code-block:: shell

    zfs create -o canmount=off zroot/boot
    zfs create -o mountpoint=legacy zroot/boot/grub
    mount -t zfs zroot/boot/grub /boot/grub

    # efi
    mount ${esp} /boot/efi
    grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=GRUB

    # or for BIOS
    grub-install --target=i386-pc /dev/sdx --recheck

If you get:

.. code-block:: shell

    /dev/sda
    Installing for i386-pc platform.
    grub-install: error: failed to get canonical path of `/dev/ata-SAMSUNG_SSD_830_Series_S0VVNEAC702110-part2'.

A workaround is to symlink the expected partition to the id

.. code-block:: shell
    
    ln -s /dev/sda2 /dev/ata-SAMSUNG_SSD_830_Series_S0VVNEAC702110-part2

Separate Partition for Kernels
###############################

An example system on Arch Linux with a separate partition for kernels would be the following:

* Boot partition mounted to ``/mnt/boot``. 
* The directory containing kernels for the active boot environment, ``/mnt/boot/env/zedenv-${boot_env}`` bind mounted to ``/boot``. 
* The grub directory ``/mnt/boot/grub`` bindmounted to ``/boot/grub``
* ``org.zedenv.grub:bootonzfs``should be set to ``no``

What this would look like during an arch Linux install would be the following: 

.. code-block:: shell

    zpool import -d /dev/disk/by-id -R /mnt vault

    mkdir -p /mnt/mnt/boot /mnt/boot
    mount /dev/sda1 /mnt/mnt/boot

    mkdir /mnt/mnt/boot/env/zedenv-default /mnt/boot/grub
    mount --bind /mnt/mnt/boot/env/zedenv-default /mnt/boot
    mount --bind /mnt/mnt/boot/grub /mnt/boot/grub

    genfstab -U -p /mnt >> /mnt/etc/fstab

    arch-chroot /mnt /bin/bash

In chroot

.. code-block:: shell

    export ZPOOL_VDEV_NAME_PATH=1

    grub-install --target=x86_64-efi --efi-directory=/mnt/boot --bootloader-id=GRUB
    grub-mkconfig -o /boot/grub/grub.cfg

An example generated grub.cfg looks like:

.. code-block:: shell

    ### BEGIN /etc/grub.d/10_linux ###
    menuentry 'Arch Linux' --class arch --class gnu-linux --class gnu --class os $menuentry_id_option 'gnulinux-simple-a1b916c0819a1863' {
            load_video
            set gfxpayload=keep
            insmod gzio
            insmod part_gpt
            insmod fat
            set root='hd0,gpt1'
            if [ x$feature_platform_search_hint = xy ]; then
              search --no-floppy --fs-uuid --set=root --hint-bios=hd0,gpt1 --hint-efi=hd0,gpt1 --hint-baremetal=ahci0,gpt1  B11F-0328
            else
              search --no-floppy --fs-uuid --set=root B11F-0328
            fi
            echo    'Loading Linux linux ...'
            linux   /env/zedenv-default/vmlinuz-linux root=ZFS=vault/sys/zedenv/ROOT/default rw  quiet
            echo    'Loading initial ramdisk ...'
            initrd  /env/zedenv-default/initramfs-linux.img
    }

Converting Existing System
~~~~~~~~~~~~~~~~~~~~~~~~~~

Create a backup. 

.. code-block:: shell

    cp -a /boot /boot.bak

Unmount ``/boot``, and remount it at ``/mnt/boot``.

.. code-block:: shell

    mkdir -p /mnt/boot
    mount /dev/sdxY /mnt/boot

Then you want to move your current kernel to ``/mnt/boot/env/zedenv-${boot_env_name}``

.. code-block:: shell

    mkdir /mnt/boot/env/zedenv-default
    mv /mnt/boot/* /mnt/boot/env/zedenv-default 

Move the grab directory back if it was also moved (or don't move it in the first place).

.. code-block:: shell

    mv /mnt/boot/env/zedenv-default/grub /mnt/boot/grub

Now bindmount the current kernel directory to ``/boot`` so that everything is where the system expects it.

.. code-block:: shell

    mount --bind /mnt/boot/env/zedenv-default /boot

Same thing with the grub directory 

.. code-block:: shell

    mount --bind /mnt/boot/grub /boot/grub 

Now everything is back to appearing how it looked originally, but things are actually stored in a different place. 

--- 

You're also probably going to want to update your fstab, if you're using Arch you can use genfstab, which requires ``arch-install-scripts``. 

.. code-block:: shell

    genfstab -U -p / 

You'll need to add the output to ``/etc/fstab.`` 

This is what an example looks like.

.. code-block:: shell

    # /dev/sda1
    UUID=B11F-0328          /mnt/boot       vfat            rw,relatime,fmask=0022,dmask=0022,codepage=437,iocharset=iso8859-1,shortname=mixed,utf8,errors=remount-ro       0 2

    /mnt/boot/env/zedenv-grub-test-3        /boot           none            rw,fmask=0022,dmask=0022,codepage=437,iocharset=iso8859-1,shortname=mixed,utf8,errors=remount-ro,bind   0 0
    /mnt/boot/grub          /boot/grub      none            rw,fmask=0022,dmask=0022,codepage=437,iocharset=iso8859-1,shortname=mixed,utf8,errors=remount-ro,bind   0 0 


Post Setup
-------------

After install, run ``zedenv --plugins``, you should see ``grub``.

Set bootloader config, options can be queried with ``zedenv get --defaults``: 

.. code-block:: shell 

    $ zedenv get --defaults
    PROPERTY                    DEFAULT    DESCRIPTION              
    org.zedenv:bootloader                  Set a bootloader plugin. 
    org.zedenv.systemdboot:esp  /mnt/efi   Set location for esp.    
    org.zedenv.grub:boot        /mnt/boot  Set location for boot.   
    org.zedenv.grub:bootonzfs   yes

Set the bootloader so it doesn't have to be declared on every usage with the ``-b`` flag.

.. code-block:: shell 

    # zedenv set org.zedenv:bootloader=grub
    
``zedenv`` will do its best to decide whether or not you are booting off of an all ZFS system, but it can also be set explicitly with ``org.zedenv.grub:bootonzfs=yes``.

Any values you have set explicitly will show up with ``zedenv get``.

Now create a new boot environment:

.. code-block:: shell 

    # zedenv create linux-4.18.12
    # zfs list
    NAME                       USED  AVAIL  REFER  MOUNTPOINT
    zroot                     2.43G  36.1G    29K  none
    zroot/ROOT                2.42G  36.1G    29K  none
    zroot/ROOT/default        2.42G  36.1G  2.42G  /
    zroot/ROOT/linux-4.18.12     1K  36.1G  2.42G  /
    zroot/data                9.36M  36.1G    29K  none
    zroot/data/home           9.33M  36.1G  9.33M  legacy

You may want to disable all of the grub generators in ``/etc/grub.d/`` except for ``00_header`` and the zedenv generator ``05_zfs_linux.py`` by removing the executable bit.
