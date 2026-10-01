; Inno Setup 6 script - run by packaging\build.ps1 after PyInstaller.
; Per-user install (no admin for VolumeX itself).
; VB-CABLE by VB-Audio ships unmodified in {app}\vbcable. If its task stays ticked it is installed silently
; (one UAC prompt). VB-Audio's license allows bundling and silent installation for donationware use, as long
; as users can identify it as VB-Audio's product and are able to donate: https://vb-audio.com/Services/licensing.htm

#define AppName "VolumeX"
#define AppVersion "0.1.0"
#ifndef AppDist
  #define AppDist "..\dist\VolumeX"
#endif
#ifndef OutDir
  #define OutDir "..\dist\installer"
#endif

[Setup]
AppId={{8C1F6E2A-5B7D-4E8A-9A51-3D2F7B6C9E10}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Sihab Sahariar
AppPublisherURL=https://sihabsahariar.com/
AppSupportURL=https://sihabsahariar.com/
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir={#OutDir}
OutputBaseFilename=VolumeX-Setup
SetupIconFile=..\assets\volumex.ico
UninstallDisplayIcon={app}\VolumeX.exe
LicenseFile=..\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Tasks]
Name: "vbcable"; Description: "Install VB-CABLE by VB-Audio - the free virtual audio device VolumeX uses to boost above 100% (donationware; Windows asks for permission)"; Check: not VBCableInstalled
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
Name: "autostart"; Description: "Start VolumeX when I sign in to Windows"

[Files]
Source: "{#AppDist}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\VolumeX.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\VolumeX.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "VolumeX"; \
    ValueData: """{app}\VolumeX.exe"" --minimized"; Tasks: autostart; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "VolumeX"; \
    Flags: uninsdeletevalue dontcreatekey
; remembers that VolumeX installed VB-CABLE, so the uninstaller can offer to remove it
Root: HKCU; Subkey: "Software\VolumeX"; ValueType: dword; ValueName: "InstalledVBCable"; ValueData: 1; \
    Tasks: vbcable; Flags: uninsdeletekey

[Run]
Filename: "{app}\vbcable\VBCABLE_Setup_x64.exe"; Parameters: "-i -h"; WorkingDir: "{app}\vbcable"; \
    Verb: "runas"; Flags: shellexec waituntilterminated; Tasks: vbcable; \
    StatusMsg: "Installing VB-CABLE by VB-Audio..."
Filename: "{app}\VolumeX.exe"; Description: "Launch VolumeX"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Route every app back to its normal device before the files go away.
Filename: "{app}\VolumeX.exe"; Parameters: "--restore --clear-closed-apps"; Flags: runhidden waituntilterminated; \
    RunOnceId: "RestoreAudio"

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\VolumeX"

[Code]
var
  CableWasPresent: Boolean;

function VBCableInstalled(): Boolean;
begin
  Result := FileExists(ExpandConstant('{sys}\drivers\vbaudio_cable64_win10.sys')) or
            FileExists(ExpandConstant('{sys}\drivers\vbaudio_cable64_win7.sys'));
end;

function InitializeSetup(): Boolean;
begin
  CableWasPresent := VBCableInstalled();
  Result := True;
end;

function NeedRestart(): Boolean;
begin
  { VB-Audio: "To finalize installation, you must reboot your computer." }
  Result := WizardIsTaskSelected('vbcable') and (not CableWasPresent);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  InstalledByUs: Cardinal;
  ResultCode: Integer;
begin
  if (CurUninstallStep = usUninstall) and VBCableInstalled() and
     RegQueryDWordValue(HKCU, 'Software\VolumeX', 'InstalledVBCable', InstalledByUs) and (InstalledByUs = 1) then
  begin
    if SuppressibleMsgBox('VolumeX installed VB-CABLE, a virtual audio device made by VB-Audio.' + #13#10#13#10 +
                          'Remove VB-CABLE as well? Choose No if other apps use it.',
                          mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES then
      ShellExec('runas', ExpandConstant('{app}\vbcable\VBCABLE_Setup_x64.exe'), '-u -h',
                ExpandConstant('{app}\vbcable'), SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;
