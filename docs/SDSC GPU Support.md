# Adding Nvidia GPU support to SDSC

1. pin kernel to avoid surprise skew, install build deps for RUNNING kernel
    ```bash
    sudo apt update && sudo apt upgrade -y
    K=$(uname -r)
    sudo apt install -y build-essential dkms linux-headers-$K pkg-config
    ```
    If upgrade installed a newer kernel than $K, reboot now and re-check uname -r
2. purge stock open drivers (mandatory for vGPU)
   You need to purge the old drivers otherwise the next step will install the wrong GRID version
    ```bash
    sudo apt purge -y cuda-drivers libnvidia-* nvidia-driver-open nvidia-dkms-open nvidia-kernel-source-open nvidia-open nvidia-firmware nvidia-kernel-common nvidia-modprobe nvidia-persistenced nvidia-settings xserver-xorg-video-nvidia || true
    sudo apt autoremove -y
    sudo dkms remove nvidia/595.71.05 --all || true
    ```
3. install GRID proprietary + DKMS
   Make sure to add the --kernel-module-type=proprietary
    ```bash
    curl -O https://sdsc-drivers.sdsc.edu/linux_nvidia_595.71.05.tar.gz
    tar -xvf linux_nvidia_595.71.05.tar.gz
    cd linux_nvidia_595.71.05/
    sudo sh NVIDIA-Linux-x86_64-595.71.05-grid.run --dkms --kernel-module-type=proprietary
    ```
    Don't reboot yet
4. verify pre-reboot
    ```bash
    sudo dkms status
    modinfo nvidia | grep -E '^version|^license'
    nvidia-smi
    ```
5. license (copies ClientConfigToken + gridd.conf, restarts nvidia-gridd)
    ```bash
    sudo bash ./nvidia_license.sh
    nvidia-smi -q | grep -i -A2 License
    systemctl is-enabled nvidia-persistenced nvidia-gridd
    ```
6. Reboot an ensure the license is still there
    ```bash
    sudo reboot
    nvidia-smi -q | grep -i -A2 License  # must survive reboot
    ```
