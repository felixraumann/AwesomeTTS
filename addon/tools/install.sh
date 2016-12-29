#!/bin/sh

# AwesomeTTS text-to-speech add-on for Anki
# Copyright (C) 2010-Present  Anki AwesomeTTS Development Team
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

if [ -z "$1" ]
then
    echo 'Please specify your Anki addons directory.' 1>&2
    echo 1>&2
    echo "    Usage: $0 <target>" 1>&2
    echo "     e.g.: $0 ~/Anki/addons" 1>&2
    exit 1
fi

target=${1%/}

case $target in
    */addons)
        ;;

    *)
        echo 'Expected target path to end in "/addons".' 1>&2
        exit 1
esac

case $target in
    /*)
        ;;

    *)
        target=$PWD/$target
esac

if [ ! -d "$target" ]
then
    echo "$target is not a directory." 1>&2
    exit 1
fi

if [ -f "$target/awesometts/config.db" ]
then
    echo 'Saving configuration...'
    saveConf=$(mktemp /tmp/config.db.XXXXXXXXXX)
    cp -v "$target/awesometts/config.db" "$saveConf"
fi

echo 'Cleaning up...'
rm -fv "$target/AwesomeTTS.py"*
rm -rfv "$target/awesometts"

oldPwd=$PWD
cd "$(dirname "$0")/.." || exit 1

echo 'Installing...'
cp -v AwesomeTTS.py "$target/AwesomeTTS.py"
mkdir -v "$target/awesometts"
cp -v awesometts/LICENSE.txt "$target/awesometts"
cp -v awesometts/*.mp3 awesometts/*.py "$target/awesometts"
mkdir -v "$target/awesometts/gui"
cp -v awesometts/gui/*.py "$target/awesometts/gui"
mkdir -v "$target/awesometts/service"
cp -v awesometts/service/*.py awesometts/service/*.js "$target/awesometts/service"

cd "$oldPwd" || exit 1

if [ -n "$saveConf" ]
then
    echo 'Restoring configuration...'
    mv -v "$saveConf" "$target/awesometts/config.db"
fi
