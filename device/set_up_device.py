#!/usr/bin/env python
"""
This script sets up a B2G device so you can test
against a dev/stage/local version of the WebPay server.
Run this inside your virtualenv:

    pip install -r device/requirements.txt

You *must* flash your device with a B2G build that
has Marionette enabled. You can grab a nightly build
from here:

    https://pvtbuilds.10allday.com/pub/10allday.com/b2g/nightly/10allday-b2g18-unagi-eng/latest/

Note the -eng suffix.

You also need the adb command on your PATH.
You can get it here: http://developer.android.com/sdk/index.html

If you want to build B2G yourself with Marionette support,
read this:

    https://developer.mozilla.org/en-US/docs/Marionette/Setup
"""
import optparse
import os
import socket
import subprocess
from subprocess import check_call
import tempfile
import time

from gaiatest import GaiaDevice, GaiaApps, GaiaData, LockScreen
from marionette import Marionette, MarionetteTouchMixin
from marionette.errors import NoSuchElementException
from marionette.errors import TimeoutException


def sh(cmd):
    return check_call(cmd, shell=True)


def wait_for_element_displayed(mc, by, locator, timeout=8):
    timeout = float(timeout) + time.time()

    while time.time() < timeout:
        time.sleep(0.5)
        try:
            if mc.find_element(by, locator).is_displayed():
                break
        except NoSuchElementException:
            pass
    else:
        raise TimeoutException(
            'Element %s not visible before timeout' % locator)


def get_installed(apps):
    apps.marionette.switch_to_frame()
    # Is this the right origin to call this from?
    res = apps.marionette.execute_async_script("""
        var req = navigator.mozApps.getInstalled();
        req.onsuccess = function _getInstalledSuccess() {
            var apps = [];
            for (var i=0; i < req.result.length; i++) {
                var ob = req.result[i];
                var app = {};
                // Make app objects JSONifiable.
                for (var k in ob) {
                    app[k] = ob[k];
                }
                apps.push(app);
            }
            marionetteScriptFinished(apps);
        };
        """)
    return res


def set_up_device(opt):
    if not opt.wifi_ssid or not opt.wifi_key or not opt.wifi_pass:
        raise ValueError('Missing --wifi options')

    mc = Marionette('localhost', opt.adb_port)
    for i in range(2):
        try:
            mc.start_session()
            break
        except socket.error:
            sh('adb forward tcp:%s tcp:%s' % (opt.adb_port, opt.adb_port))
    if opt.shell:
        from pdb import set_trace
        set_trace()
        return

    # watch out! This is how gaiatest does it.
    mc.__class__ = type('Marionette', (Marionette, MarionetteTouchMixin), {})
    device = GaiaDevice(mc)

    device.restart_b2g()

    apps = GaiaApps(mc)
    data_layer = GaiaData(mc)
    lockscreen = LockScreen(mc)
    mc.setup_touch()

    lockscreen.unlock()
    apps.kill_all()

    data_layer.enable_wifi()
    if opt.wifi_key == 'WPA-PSK':
        pass_key = 'psk'
    elif opt.wifi_key == 'WEP':
        pass_key = 'wep'
    else:
        assert 0, 'unknown key management'
    data = {'ssid': opt.wifi_ssid, 'keyManagement': opt.wifi_key,
            pass_key: opt.wifi_pass}
    data_layer.connect_to_wifi(data)

    mc.switch_to_frame()
    all_apps = set(a['manifest']['name'] for a in get_installed(apps))
    if 'Marketplace Dev' not in all_apps:
        mc.execute_script(
            'navigator.mozApps.install'
            '("https://marketplace-dev.10allday.com/manifest.webapp");')
        wait_for_element_displayed(mc, 'id', 'app-install-install-button')
        yes = mc.find_element('id', 'app-install-install-button')
        mc.tap(yes)
        wait_for_element_displayed(mc, 'id', 'system-banner')

    print 'Pushing payment prefs'
    sh('adb shell stop b2g')
    sh('adb push "%s" /data/local/user.js' % (
        os.path.join(os.path.dirname(__file__), 'payment-prefs.js')))
    sh('adb shell start b2g')

    print 'When your device reboots, Marketplace Dev will be installed'


def http_log_restart(opt):
    sh('adb shell stop b2g')
    print "restarting with HTTP logging enabled"
    print "press control+C to quit"
    sh('adb shell rm /data/local/tmp/http.log')
    p = subprocess.Popen("""adb shell <<SHELL
#export NSPR_LOG_MODULES=timestamp,nsHttp:5,nsSocketTransport:5,nsHostResolver:5
export NSPR_LOG_MODULES=nsHttp:3
export NSPR_LOG_FILE=/data/local/tmp/http.log
/system/bin/b2g.sh

SHELL
        """, shell=True)  # noqa
    try:
        print 'Get output with adb logcat'
        p.wait()
    except KeyboardInterrupt:
        p.kill()
        p.wait()

    tmp = tempfile.gettempdir()
    os.chdir(tmp)
    sh('adb pull /data/local/tmp/http.log')
    print '*' * 80
    print 'Log file: %s/http.log' % tmp
    print '*' * 80
    sh('adb reboot')


def main():
    p = optparse.OptionParser(usage='%prog [options]\n' + __doc__)
    p.add_option('-p', '--adb-port', default=2828, type=int,
                 help='adb port to forward on the device. Default: %default')
    p.add_option('-s', '--shell', action='store_true',
                 help='Drop into an interactive shell')
    p.add_option('-w', '--wifi-ssid', help='WiFi SSID to connect to')
    p.add_option('-k', '--wifi-key', help='WiFi key management. '
                                          'Options: WPA-PSK, WEP')
    p.add_option('-P', '--wifi-pass', help='WiFi password')

    # TODO: this is probably a good reason to switch to argparse.
    p.add_option('--http-log', action='store_true',
                 help='Restart the device with HTTP logging enabled. ')

    (opt, args) = p.parse_args()

    if opt.http_log:
        http_log_restart(opt)
    else:
        set_up_device(opt)


if __name__ == '__main__':
    main()
