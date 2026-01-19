# morphix-prototype
A prototype for Morphix, a universal file conversion and compression desktop application, meant to make both conversion and compression an easy, one-button job for images, videos and audio files.

![](docs/BasicLogic.png)

# Setup
First, make sure you have your virtual environment setup.

Create the virtual environment locally, selecting `[y]` for every option, then verify it exists.
This step installs a bunch of dependencies by default, which cover what need to be installed to run morphix as it is currently.

```py
conda create --name env python=3.13.9
conda info --envs
```

Activate the environment:
```py
conda activate env
```

Change python version, if you wish:
```py
conda uninstall python
conda install python=3.13.9
```

Deactivate then delete the venv
```
conda activate
conda remove --name env --all
```

# Example instruction

Python Morphix.py vid1.mp4 --max-mb 1 --output vid1_new.mp4       
