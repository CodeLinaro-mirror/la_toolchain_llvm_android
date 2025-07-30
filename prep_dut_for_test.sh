#!/system/bin/sh

# The script is used to perpare a device for testing.
# It should only be run on-device.

set_android_max() {
	# Airplane mode
	settings put global airplane_mode_on 1
	am broadcast -a android.intent.action.AIRPLANE_MODE

	# Power
	svc power stayon true
	settings put system screen_off_timeout 172800000
	settings put global stay_on_while_plugged_in 7

	# Prevent background jobs
	settings put global package_verifier_enable 0
	pm disable com.android.vending
	svc bluetooth disable
	am start -a android.intent.action.MAIN -c android.intent.category.HOME
	am start -a com.android.setupwizard.EXIT
	sleep 1
	input keyevent KEYCODE_WAKEUP
	sleep 1
	input keyevent HOME
}

stop_powerhal() {
	setprop vendor.powerhal.init 0
	setprop ctl.restart vendor.power-hal-aidl
}

disable_tskin() {
	setprop vendor.disable.thermal.control 1
}

set_cpu() {
	for path in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
		echo powersave >$path
	done
}

set_android_max
stop_powerhal
disable_tskin
set_cpu
