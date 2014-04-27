# -*- coding: utf-8 -*-

# AwesomeTTS text-to-speech add-on for Anki
#
# Copyright (C) 2010-2014  Anki AwesomeTTS Development Team
# Copyright (C) 2010-2012  Arthur Helfstein Fragoso
# Copyright (C) 2013-2014  Dave Shifflett
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

"""
Interaction with the Anki reviewer

This module is mostly headless. It lives in the "gui" package, however,
because interacts with the GUI components of Anki and it also spawns
alert windows. It also may have more visual components in the future.
"""

__all__ = ['Reviewer']

from BeautifulSoup import BeautifulSoup


# n.b. Previously, before playing handlers, these event handlers checked to
# make sure that 'not sound.hasSound()'. I am guessing that this was done
# because AwesomeTTS did not know how to properly deal with multiple sounds
# at the time and they would play simultaneously.
#
# FIXME. It is possible, I suppose, that people might have the exact same
# audio file on a card via a [sound:xxx] tag as they do as a <tts> template
# tag. We can probably detect this by seeing if two of the same hashed
# filename end up in the queue (and I say "filename" because one would be
# coming from the media directory and another would be coming from the cache
# directory). This would probably need to be fixed in the router by having the
# router examine whether the exact same hashed filename is in the Anki
# playback queue already or looking at any [sound:xxx] tags on the card before
# playing back the on-the-fly sound.
#
# A similar problem probably exists in reviewer_key_handler for folks who
# includes their question card template within their answer card template and
# whose tts_key_q == tts_key_a.
#
# Unfortunately, it looks like inspecting anki.sound.mplayerQueue won't work
# out on Windows because the path gets blown away by the temporary file
# creation code.
#
# ALTERNATIVELY, if examination of the tag or playback queue turns out to not
# work out so well, this could become two checkbox options on the "On-the-Fly
# Mode" tab for both question and answer sides.


class Reviewer(object):
    """
    Provides interaction for on-the-fly functionality and Anki's
    reviewer mode.
    """

    __slots__ = [
        '_addon',
        '_alerts',
        '_normalize',
        '_parent',
        '_playback',
    ]

    def __init__(self, addon, playback, alerts, parent):
        self._addon = addon
        self._alerts = alerts
        self._parent = parent
        self._playback = playback

    def play_html(self, html):
        """
        Read in the passed HTML, attempt to discover <tts> tags in it,
        and pass them to play() for processing.

        TODO: Look at adding back support for [?tts] tags.
        """

        for tag in BeautifulSoup(html)('tts'):
            text = ''.join(tag.findAll(text=True))
            if not text:
                continue

            attr = dict(tag.attrs)

            try:
                svc_id = attr.pop('service')
            except KeyError:
                self._alerts(
                    "This tag needs a 'service' attribute:\n%s" % str(tag),
                    self._parent,
                )
                continue

            self._addon.router(
                svc_id=svc_id,
                text=text,
                options=attr,
                callbacks=dict(
                    okay=self._playback,
                    fail=lambda exception: self._alerts(
                        "Unable to play this tag:\n%s\n\n%s" %
                        (str(tag), exception.message),
                        self._parent,
                    ),
                ),
            )
