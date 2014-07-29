/*
 * AwesomeTTS text-to-speech add-on for Anki
 *
 * Copyright (C) 2014       Anki AwesomeTTS Development Team
 * Copyright (C) 2014       Dave Shifflett
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

/**
 * Really simple JScript gateway for talking to the Microsoft Speech API.
 *
 * cscript sapi5.js voice-list
 * cscript sapi5.js speech-output <file> <rate> <vol> <hex_voice> <hex_phrase>
 */

/*globals WScript*/


var argv = WScript.arguments;

if (typeof argv !== 'object') {
    throw new Error("Unable to read from the arguments list");
}


var argc = argv.count();

if (typeof argc !== 'number' || argc < 1) {
    throw new Error("Expecting the command to execute");
}


var command = argv.item(0);
var options = {};

if (command === 'voice-list') {
    if (argc > 1) {
        throw new Error("Unexpected extra arguments for voice-list");
    }
} else if (command === 'speech-output') {
    if (argc !== 6) {
        throw new Error("Expecting exactly 5 arguments for speech-output");
    }

    var getWavePath = function (path) {
        if (path.length < 5 || !/\.wav$/i.test(path)) {
            throw new Error("Expecting a path ending in .wav");
        }

        return path;
    };

    var getInteger = function (str, lower, upper, what) {
        if (!/^-?\d{1,3}$/.test(str)) {
            throw new Error("Expected an integer for " + what);
        }

        var value = parseInt(str, 10);

        if (value < lower || value > upper) {
            throw new Error("Value for " + what + " out of range");
        }

        return value;
    };

    var getUnicodeFromHex = function (hex, what) {
        if (typeof hex !== 'string' || hex.length < 4 || hex.length % 4 !== 0) {
            throw new Error("Expected quad-chunked hex string for " + what);
        }

        var i;
        var unicode = [];

        for (i = 0; i < hex.length; i += 4) {
            unicode.push(parseInt(hex.substr(i, 4), 16));
        }

        return String.fromCharCode.apply('', unicode);
    };

    // See also sapi5.py when adjusting any of these
    options.file = getWavePath(argv.item(1));
    options.rate = getInteger(argv.item(2), -10, 10, "rate");
    options.volume = getInteger(argv.item(3), 1, 100, "volume");
    options.voice = getUnicodeFromHex(argv.item(4), "voice");
    options.phrase = getUnicodeFromHex(argv.item(5), "phrase");
} else {
    throw new Error("Unrecognized command sent");
}


var sapi = WScript.createObject('SAPI.SpVoice');

if (typeof sapi !== 'object') {
    throw new Error("SAPI does not seem to be available");
}


var voices = sapi.getVoices();

if (typeof voices !== 'object') {
    throw new Error("Voice retrieval does not seem to be available");
}

if (typeof voices.count !== 'number' || voices.count < 1) {
    throw new Error("There does not seem to be any voices installed");
}


var i;

if (command === 'voice-list') {
    WScript.echo('__AWESOMETTS_VOICE_LIST__');

    for (i = 0; i < voices.count; ++i) {
        WScript.echo(voices.item(i).getAttribute('name'));
    }
} else if (command === 'speech-output') {
    var found = false;
    var voice;

    for (i = 0; i < voices.count; ++i) {
        voice = voices.item(i);

        if (voice.getAttribute('name') === options.voice) {
            found = true;
            sapi.voice = voice;
            break;
        }
    }

    if (!found) {
        throw new Error("Could not find the specified voice.");
    }

    var audioOutputStream = WScript.createObject('SAPI.SpFileStream');

    if (typeof audioOutputStream !== 'object') {
        throw new Error("Unable to create an output file");
    }

    audioOutputStream.open(options.file, 3 /* SSFMCreateForWrite */);

    sapi.audioOutputStream = audioOutputStream;
    sapi.rate = options.rate;
    sapi.volume = options.volume;

    sapi.speak(options.phrase);
}