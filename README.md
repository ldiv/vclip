
vclip
=======

vclip is a Python program which functions as a wrapper for FFMPEG to easily clip portions of a video and merge into one file.

Requirements
------------

+ Python 3
+ ffmpeg (installed and on the system path)


Usage
-----

	python3 vclip.py <input_video_file_name> -i interval [intervals ...]

	interval format: [HH:]MM:SS-[HH:]MM:SS


Example
-------

At the command line:

	usr@host $ python3 vclip.py testvid.mp4 -i 0:44-0:54 5:40-5:45 6:20-6:30
	
Output:	

	Intervals to clip [00:00:44-00:00:54, 00:05:40-00:05:45, 00:06:20-00:06:30]
	Processing subclip 1 out of 3
	Processing subclip 2 out of 3
	Processing subclip 3 out of 3
	Merging subclips
	Result saved to /output_path/testvid_clip.mp4
	usr@host $


The default output path--where the edited file gets written to--is currently the same directory as the one where the program runs.  I will shortly be adding an option to pass this as a parameter.


License
-------

MIT License

