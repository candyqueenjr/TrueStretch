"""Intel graphics through the Intel Graphics Control Library (ControlLib.dll, part of every recent Intel driver):
add a custom resolution and set scaling to Stretched - what Intel Graphics Command Center does by hand.
Raises OSError when the library or the screen isn't there."""

import ctypes
from ctypes import POINTER, byref, c_bool, c_float, c_uint8, c_uint16, c_uint32, c_uint64, c_void_p

from .paths import log

CTL_SUCCESS = 0
CUSTOM_MODE_EXISTS = (0x4800001A, 0x4800001B)      # standard / non-custom mode with that size already exists
OP_GET, OP_ADD = 0, 1
SCALING_IDENTITY, SCALING_CENTERED, SCALING_STRETCHED, SCALING_ASPECT = 1, 2, 4, 8
DISPLAY_ACTIVE = 1


class _AppId(ctypes.Structure):
    _fields_ = [("Data1", c_uint32), ("Data2", c_uint16), ("Data3", c_uint16), ("Data4", c_uint8 * 8)]


class _InitArgs(ctypes.Structure):
    _fields_ = [("Size", c_uint32), ("Version", c_uint8), ("AppVersion", c_uint32), ("flags", c_uint32),
                ("SupportedVersion", c_uint32), ("ApplicationUID", _AppId)]


class _GenericVoid(ctypes.Structure):
    _fields_ = [("pData", c_void_p), ("size", c_uint32)]


class _EncoderId(ctypes.Union):
    _fields_ = [("WindowsDisplayEncoderID", c_uint32), ("DisplayEncoderID", _GenericVoid)]


class _Revision(ctypes.Structure):
    _fields_ = [("major", c_uint8), ("minor", c_uint8), ("revision", c_uint8)]


class _Timing(ctypes.Structure):
    _fields_ = [("Size", c_uint32), ("Version", c_uint8), ("PixelClock", c_uint64), ("HActive", c_uint32),
                ("VActive", c_uint32), ("HTotal", c_uint32), ("VTotal", c_uint32), ("HBlank", c_uint32),
                ("VBlank", c_uint32), ("HSync", c_uint32), ("VSync", c_uint32), ("RefreshRate", c_float),
                ("SignalStandard", c_uint32), ("VicId", c_uint8)]


class _DisplayProps(ctypes.Structure):
    _fields_ = [("Size", c_uint32), ("Version", c_uint8), ("Os_display_encoder_handle", _EncoderId),
                ("Type", c_uint32), ("AttachedDisplayMuxType", c_uint32), ("ProtocolConverterOutput", c_uint32),
                ("SupportedSpec", _Revision), ("SupportedOutputBPCFlags", c_uint32),
                ("ProtocolConverterType", c_uint32), ("DisplayConfigFlags", c_uint32),
                ("FeatureEnabledFlags", c_uint32), ("FeatureSupportedFlags", c_uint32),
                ("AdvancedFeatureEnabledFlags", c_uint32), ("AdvancedFeatureSupportedFlags", c_uint32),
                ("Display_Timing_Info", _Timing), ("ReservedFields", c_uint32 * 16)]


class _Scaling(ctypes.Structure):
    _fields_ = [("Size", c_uint32), ("Version", c_uint8), ("Enable", c_bool), ("ScalingType", c_uint32),
                ("CustomScalingX", c_uint32), ("CustomScalingY", c_uint32), ("HardwareModeSet", c_bool),
                ("PreferredScalingType", c_uint32)]


class _ScalingCaps(ctypes.Structure):
    _fields_ = [("Size", c_uint32), ("Version", c_uint8), ("SupportedScaling", c_uint32)]


class _SrcMode(ctypes.Structure):
    _fields_ = [("SourceX", c_uint32), ("SourceY", c_uint32)]


class _CustomModeArgs(ctypes.Structure):
    _fields_ = [("Size", c_uint32), ("Version", c_uint8), ("CustomModeOpType", c_uint32),
                ("NumOfModes", c_uint32), ("pCustomSrcModeList", POINTER(_SrcMode))]


def _sized(cls, version=0):
    obj = cls()
    obj.Size = ctypes.sizeof(cls)
    obj.Version = version
    return obj


class IntelOutput:
    def __init__(self, api, handle, target_id, width, height):
        self.api, self.handle, self.target_id, self.width, self.height = api, handle, target_id, width, height

    def __repr__(self):
        return f"IntelOutput(target={self.target_id}, {self.width}x{self.height})"


class IntelApi:
    def __init__(self):
        try:
            self.dll = ctypes.CDLL("ControlLib.dll")
        except OSError as exc:
            raise OSError("Intel Graphics Control Library isn't installed (old Intel driver)") from exc
        args = _sized(_InitArgs)
        args.AppVersion = (1 << 16) | 1
        self.handle = c_void_p()
        try:
            self._call("ctlInit", byref(args), byref(self.handle))
        except OSError as exc:
            # Older drivers only speak 1.0: they report what they support, so ask again with that.
            if not (len(exc.args) > 1 and exc.args[1] == 0x40000009 and args.SupportedVersion
                    and args.SupportedVersion != args.AppVersion):
                raise
            supported = args.SupportedVersion
            args = _sized(_InitArgs)
            args.AppVersion = supported
            self._call("ctlInit", byref(args), byref(self.handle))

    def _call(self, name, *args):
        fn = getattr(self.dll, name, None)
        if fn is None:
            raise OSError(f"{name} isn't in this Intel driver")
        fn.restype = c_uint32
        result = fn(*args)
        if result != CTL_SUCCESS:
            raise OSError(f"{name} failed ({result:#x})", result)
        return result

    def close(self):
        try:
            self.dll.ctlClose(self.handle)
        except Exception:
            pass

    def outputs(self):
        """Active Intel display outputs; target_id is the Windows display target id (CCD)."""
        count = c_uint32(0)
        self._call("ctlEnumerateDevices", self.handle, byref(count), None)
        devices = (c_void_p * count.value)()
        self._call("ctlEnumerateDevices", self.handle, byref(count), devices)
        found = []
        for dev in devices[:count.value]:
            n = c_uint32(0)
            try:
                self._call("ctlEnumerateDisplayOutputs", c_void_p(dev), byref(n), None)
                outs = (c_void_p * n.value)()
                self._call("ctlEnumerateDisplayOutputs", c_void_p(dev), byref(n), outs)
            except OSError:
                continue
            for out in outs[:n.value]:
                props = _sized(_DisplayProps)
                props.Display_Timing_Info.Size = ctypes.sizeof(_Timing)
                try:
                    self._call("ctlGetDisplayProperties", c_void_p(out), byref(props))
                except OSError:
                    continue
                if props.DisplayConfigFlags & DISPLAY_ACTIVE:
                    t = props.Display_Timing_Info
                    found.append(IntelOutput(self, c_void_p(out), props.Os_display_encoder_handle
                                             .WindowsDisplayEncoderID, t.HActive, t.VActive))
        return found

    def output_for(self, target_id):
        return next((o for o in self.outputs() if o.target_id == target_id), None)

    def custom_modes(self, output):
        args = _sized(_CustomModeArgs)
        args.CustomModeOpType = OP_GET
        self._call("ctlGetSetCustomMode", output.handle, byref(args))
        if not args.NumOfModes:
            return []
        modes = (_SrcMode * args.NumOfModes)()
        args.pCustomSrcModeList = ctypes.cast(modes, POINTER(_SrcMode))
        self._call("ctlGetSetCustomMode", output.handle, byref(args))
        return [(m.SourceX, m.SourceY) for m in modes[:args.NumOfModes]]

    def add_custom_mode(self, output, width, height):
        """True when added, False when the size already exists."""
        mode = _SrcMode(width, height)
        args = _sized(_CustomModeArgs)
        args.CustomModeOpType = OP_ADD
        args.NumOfModes = 1
        args.pCustomSrcModeList = ctypes.pointer(mode)
        try:
            self._call("ctlGetSetCustomMode", output.handle, byref(args))
        except OSError as exc:
            if len(exc.args) > 1 and exc.args[1] in CUSTOM_MODE_EXISTS:
                return False
            raise
        log.info("Intel: custom resolution %sx%s added", width, height)
        return True

    def scaling(self, output):
        s = _sized(_Scaling, 1)
        self._call("ctlGetCurrentScaling", output.handle, byref(s))
        return s.ScalingType if s.Enable else SCALING_IDENTITY

    def supports_stretch(self, output):
        caps = _sized(_ScalingCaps)
        self._call("ctlGetSupportedScalingCapability", output.handle, byref(caps))
        return bool(caps.SupportedScaling & SCALING_STRETCHED)

    def set_scaling(self, output, scaling_type=SCALING_STRETCHED):
        s = _sized(_Scaling, 1)
        s.Enable = True
        s.ScalingType = scaling_type
        s.HardwareModeSet = False
        self._call("ctlSetCurrentScaling", output.handle, byref(s))
        log.info("Intel: scaling set to %s", scaling_type)
