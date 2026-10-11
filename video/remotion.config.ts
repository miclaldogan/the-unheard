import {Config} from '@remotion/cli/config';

Config.setVideoImageFormat('jpeg');
Config.setJpegQuality(95);
Config.setOverwriteOutput(true);
Config.setBrowserExecutable('/usr/sbin/google-chrome-stable');
Config.setConcurrency(3);
