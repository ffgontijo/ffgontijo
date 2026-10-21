# Static analysis of Mouse Drive Beta.exe

No uploaded executable was executed. The PE CLR metadata and IL were parsed with dnfile/dncil, then independently decompiled with ILSpyCmd 9.1.0.7988. Native embedded HIDUsb.dll exports were statically disassembled with GNU objdump. `decompiled/` is reference material extracted from the user's binary, not a clean-room application implementation.

## Proven mappings

* `DriverLib/KeyFunMapDriver.cs:61`: `SetChangeConfigKey(ref KeyFunMap)` writes type 9, param1 0, param2 0.
* `Mouse_Drive_Beta/KeyFunctionTypeEnum.cs`: enum value 9 is `ProfileSwitch`.
* `FileManager/LanguageFile.cs`: button function menu entries are loaded directly from XML `KeyFunction/name`; the supplied XML omits type 9. There is no managed capability check for type 9.
* `FormMain.ButtonFunctionInit`: `KeyNumber / 10` is number of buttons; `KeyNumber % 10 == 1` enables scroll mapping. Config `KeyNumber=80` means eight physical buttons, no scroll mapping. It is NOT a capability bitmask.
* Config KeyParam6 has logical index 9, KeyParam7 has logical index 10. Thus B6 is index 9 and B7 is index 10; B5 index 3 can remain untouched.
* Native HIDUsb `ProtocolDataParser` code at 0x1800074a0: button records start memory 0x60, each four bytes: type, param1, param2, checksum. `BufferToKeyFunMap` at 0x180007450 validates `sum(record) == 0x55 (mod 256)`. B7 record is address 0x88 and experimental profile-switch value is `09 00 00 4C`.

## Profile selection and uncertainty

* `FormMain.customComboBox_Config_OnSelectedIndexChanged` invokes `UsbServer.SetCurrentConfig`.
* Native `UsbServer_ReadConfig` at 0x180010CC0 creates report `08 0E 00 00 00 00 ... checksum` (flags may change length field high bit for alternate endpoint). Native `UsbServer_SetCurrentConfig` at 0x180010DB0 creates report `08 0F 00 00 00 01 index ... checksum`. There is no count, enabled-mask, source-profile, or target-profile parameter beyond the selected index in this API.
* `FormMain.onUsbDataReceived`, GetCurrentConfig case (decompiled line 1350): if response payload is null the UI hardcodes one profile; if nonnull it hardcodes four and selects response byte 0. `UnchangeProfile` is only a local UI restriction, not a device operation. XML has Profiles 1..4.
* No feature enabling only two cycle slots was found. A four-slot cycle could provide two effective alternating configurations using mac, Windows, mac, Windows, but only IF current firmware implements type 9.
* Presence of the generic type 9 method does NOT prove this specific mouse's firmware implements it. The supplied updater image declares different USB identifiers/protocol, and its correspondence to the captured revision was not established, so it cannot settle this question. Hardware testing is required. A bounded B7-record test with backup/restore is justified as an experiment, never as a guaranteed supported feature.

## Shortcut encoding

* `KeyboardCodes.cs`: normal `1` HID code 30 (0x1e); PrintScreen code70 (0x46). LWin is `HID_CODE_TYPE.Modify=0`, code8 (GUI modifier bitmask), not normal key usage0xe3. This modifier produces Command on normal macOS HID mapping.
* `ValueConvert.App_AddShortCutKey`: append all presses, then releases in reverse order. `ShortcutKeyToBuffer` native export 0x1800096b0 emits count followed by three-byte events: high bit0x80 press or0x40 release OR'ed with type; then two little-endian value bytes. Append checksum making sum0x55. Shortcut record area is `0x100+index*0x20`, so B6 index9 is0x220.
* mac B6 `Command+1` meaningful bytes: `04 80 08 00 81 1E 00 41 1E 00 40 08 00 83` (checksum included). Windows B6 PrintScreen: `02 81 46 00 41 46 00 05`. Rest of 32-byte record may be preserved or padded; parser validates only through checksum after count events.
* B6 mapping record at0x84 must be `05 00 00 50` to select associated shortcut slot.

## Other protocol findings

* Managed `UsbCommandID` enum proves opcode0x12 is ReadVersionID, not maximum-profile count. Response `04 01` encodes firmware version, not four profiles plus capability1.
* op0x01 is EncryptionData / device identification. Native at0x18000f160 makes count8 request with random first4 payload bytes, final4 zero. FormMain processes result through native `CS_GetDeviceInfo`. No extra host acknowledgement beyond ordinary PCDriverStatus op2 is exposed in managed layer. Native CS_GetDeviceInfo at0x180006fa0 copies payload[4],payload[5],payload[6] to CID,MID,DeviceType, corresponding to full report indices10,11,12. Captured identity17,29,02 matches configured CID23,MID41,DeviceType2.
* Physical path selection uses `FindHidDevicesByDeviceId(VID,PID,Interfaceid=1,Deviceid=5)` from Config.ini. No HID UsagePage predicate is exposed by managed code.

## Evidence files

* `profile_il.txt`, `button_il.txt`, `all_il.txt` contain original IL instructions and metadata token names.
* `decompiled/DriverLib/KeyFunMapDriver.cs`, `decompiled/DriverLib/KeyboardCodes.cs`, `decompiled/Mouse_Drive_Beta/ValueConvert.cs`, `decompiled/Mouse_Drive_Beta/FormMain.cs` provide readable corroboration.
* `costura64.hidusb.dll` and `costura32.hidusb32.dll` are user binary's extracted embedded native libraries; do not redistribute them as part of the new portable app.
