; Inno Setup 6: instalador del hub de Checkpoint para Windows (modo nativo, sin Docker).
; Compilar (desde la raíz del repositorio, tras PyInstaller):
;   iscc /DAppVersion=2.5.0 packaging\windows\installer.iss
; Entrada: packaging\windows\dist\checkpoint\ (checkpoint.spec). Salida: packaging\windows\Output\Checkpoint-Setup-<versión>.exe
;
; Instalación POR USUARIO (sin Administrador): así «Actualizar ahora» puede relanzar el instalador sin UAC y la Tarea
; Programada de autoarranque corre con el mismo usuario. Datos y .env en %APPDATA%\checkpoint (no se tocan al actualizar).
; Parámetros de instalación silenciosa (/VERYSILENT):
;   /NOLOGIN=1                 arranca sin usuario ni contraseña (solo 127.0.0.1)
;   /CPUSER=<usuario> /CPPASSWORD=<contraseña>   escribe esas credenciales
;   (sin ninguno: se conserva el .env existente; si no hay .env, arranca sin login en 127.0.0.1)
; Sin firma de código: SmartScreen avisará (ver el texto de bienvenida y la documentación).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6D1F3C52-7B7E-4C0B-9E5A-C4E0C8A1B2F7}
AppName=Checkpoint
AppVersion={#AppVersion}
AppPublisher=Checkpoint
DefaultDirName={localappdata}\Programs\Checkpoint
DefaultGroupName=Checkpoint
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=Checkpoint-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no
UninstallDisplayName=Checkpoint
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
spanish.WelcomeLabel1=Instalar Checkpoint {#AppVersion}
english.WelcomeLabel1=Install Checkpoint {#AppVersion}
spanish.WelcomeLabel2=Este asistente instala el hub de Checkpoint en este equipo, sin Docker. Incluye el plugin para Steam Deck.%n%nEste instalador no está firmado. Windows puede mostrar «Windows protegió su PC»: pulsa «Más información» y luego «Ejecutar de todos modos».
english.WelcomeLabel2=This wizard installs the Checkpoint hub on this computer, without Docker. It includes the Steam Deck plugin.%n%nThis installer is not signed. Windows may show “Windows protected your PC”: click “More info”, then “Run anyway”.
spanish.FinishedLabel=Checkpoint está instalado y se abrirá en http://127.0.0.1:8088.
english.FinishedLabel=Checkpoint is installed and will open at http://127.0.0.1:8088.

[CustomMessages]
spanish.AccessTitle=Acceso a Checkpoint
english.AccessTitle=Checkpoint access
spanish.AccessText=Elige el usuario y la contraseña para entrar en la web.
english.AccessText=Choose the username and password to sign in to the web app.
spanish.User=Usuario
english.User=Username
spanish.Password=Contraseña
english.Password=Password
spanish.Repeat=Repetir contraseña
english.Repeat=Repeat password
spanish.Generate=Generar contraseña
english.Generate=Generate password
spanish.Generated=Contraseña generada: cópiala ahora, no se vuelve a mostrar.
english.Generated=Password generated: copy it now, it will not be shown again.
spanish.NoLogin=Arrancar sin usuario ni contraseña (solo en este equipo)
english.NoLogin=Start without username or password (this computer only)
spanish.NoLoginHelp=Solo se podrá abrir desde este equipo (127.0.0.1). Cualquier persona con acceso a este equipo podrá entrar.
english.NoLoginHelp=It can only be opened from this computer (127.0.0.1). Anyone with access to this computer will be able to sign in.
spanish.NeedUser=Escribe un usuario.
english.NeedUser=Enter a username.
spanish.NeedPassword=La contraseña no puede estar vacía.
english.NeedPassword=The password cannot be empty.
spanish.Mismatch=Las contraseñas no coinciden.
english.Mismatch=The passwords do not match.
spanish.OpenNow=Abrir Checkpoint ahora
english.OpenNow=Open Checkpoint now
spanish.DeleteData=¿Borrar también tus datos (configuración y versiones de saves) de %APPDATA%\checkpoint?
english.DeleteData=Also delete your data (configuration and save versions) from %APPDATA%\checkpoint?

[Files]
Source: "dist\checkpoint\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Checkpoint"; Filename: "{app}\checkpoint.exe"; Parameters: "--open"
Name: "{group}\Detener Checkpoint"; Filename: "{sys}\taskkill.exe"; Parameters: "/IM checkpoint.exe /F"; Flags: runminimized

[Run]
Filename: "{app}\checkpoint.exe"; Parameters: "--open"; Description: "{cm:OpenNow}"; Flags: nowait postinstall skipifsilent
; Instalación silenciosa (actualización con un clic): vuelve a arrancar el hub sin abrir el navegador.
Filename: "{app}\checkpoint.exe"; Flags: nowait runhidden; Check: WizardSilent

[UninstallRun]
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN Checkpoint /F"; Flags: runhidden; RunOnceId: "DelTask"
Filename: "{sys}\taskkill.exe"; Parameters: "/IM checkpoint.exe /F"; Flags: runhidden; RunOnceId: "KillHub"

[Code]
const
  PwAlphabet = 'abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789';

var
  AccessPage: TWizardPage;
  UserEdit: TNewEdit;
  PassEdit, Pass2Edit: TPasswordEdit;
  GenButton: TNewButton;
  GenLabel: TNewStaticText;
  NoLoginCheck: TNewCheckBox;
  HelpLabel: TNewStaticText;

function EnvPath: String;
begin
  Result := ExpandConstant('{userappdata}\checkpoint\.env');
end;

procedure UpdateAccessControls;
var
  login: Boolean;
begin
  login := not NoLoginCheck.Checked;
  UserEdit.Enabled := login;
  PassEdit.Enabled := login;
  Pass2Edit.Enabled := login;
  GenButton.Enabled := login;
end;

procedure NoLoginClick(Sender: TObject);
begin
  UpdateAccessControls;
end;

{ Contraseña aleatoria de 24 caracteres con el generador criptográfico de Windows (PowerShell). Si falla, Random(). }
function NewPassword: String;
var
  tmp, cmd: String;
  rc: Integer;
  lines: TArrayOfString;
  i: Integer;
begin
  Result := '';
  tmp := ExpandConstant('{tmp}\pw.txt');
  cmd := '/C powershell.exe -NoProfile -Command "-join ((1..24) | ForEach-Object { ''' + PwAlphabet +
         '''[[System.Security.Cryptography.RandomNumberGenerator]::GetInt32(' + IntToStr(Length(PwAlphabet)) + ')] })" > "' + tmp + '"';
  if Exec(ExpandConstant('{cmd}'), cmd, '', SW_HIDE, ewWaitUntilTerminated, rc) and (rc = 0) then
    if LoadStringsFromFile(tmp, lines) and (GetArrayLength(lines) > 0) then
      Result := Trim(lines[0]);
  DeleteFile(tmp);
  if Length(Result) <> 24 then
  begin
    Result := '';
    for i := 1 to 24 do
      Result := Result + Copy(PwAlphabet, Random(Length(PwAlphabet)) + 1, 1);
  end;
end;

procedure GenerateClick(Sender: TObject);
var
  pw: String;
begin
  pw := NewPassword;
  PassEdit.Text := pw;
  Pass2Edit.Text := pw;
  GenLabel.Caption := CustomMessage('Generated');
  { La contraseña se muestra en claro un momento para poder copiarla. }
  PassEdit.Password := False;
end;

procedure InitializeWizard;
var
  y: Integer;
  Lbl: TNewStaticText;
begin
  AccessPage := CreateCustomPage(wpWelcome, CustomMessage('AccessTitle'), CustomMessage('AccessText'));
  y := 0;
  Lbl := TNewStaticText.Create(AccessPage);
  Lbl.Parent := AccessPage.Surface; Lbl.Caption := CustomMessage('User'); Lbl.Top := y; Lbl.Left := 0;
  UserEdit := TNewEdit.Create(AccessPage);
  UserEdit.Parent := AccessPage.Surface;
  UserEdit.Top := y + ScaleY(16); UserEdit.Width := AccessPage.SurfaceWidth div 2; UserEdit.Text := 'checkpoint';
  y := y + ScaleY(48);
  Lbl := TNewStaticText.Create(AccessPage);
  Lbl.Parent := AccessPage.Surface; Lbl.Caption := CustomMessage('Password'); Lbl.Top := y; Lbl.Left := 0;
  PassEdit := TPasswordEdit.Create(AccessPage);
  PassEdit.Parent := AccessPage.Surface;
  PassEdit.Top := y + ScaleY(16); PassEdit.Width := AccessPage.SurfaceWidth div 2;
  PassEdit.MaxLength := 72;  { el hub trunca la contraseña a 72 bytes (bcrypt) }
  GenButton := TNewButton.Create(AccessPage);
  GenButton.Parent := AccessPage.Surface;
  GenButton.Caption := CustomMessage('Generate');
  GenButton.Left := PassEdit.Width + ScaleX(8); GenButton.Top := PassEdit.Top - ScaleY(2);
  GenButton.Width := ScaleX(140); GenButton.Height := ScaleY(23);
  GenButton.OnClick := @GenerateClick;
  y := y + ScaleY(48);
  Lbl := TNewStaticText.Create(AccessPage);
  Lbl.Parent := AccessPage.Surface; Lbl.Caption := CustomMessage('Repeat'); Lbl.Top := y; Lbl.Left := 0;
  Pass2Edit := TPasswordEdit.Create(AccessPage);
  Pass2Edit.Parent := AccessPage.Surface;
  Pass2Edit.Top := y + ScaleY(16); Pass2Edit.Width := AccessPage.SurfaceWidth div 2;
  Pass2Edit.MaxLength := 72;
  GenLabel := TNewStaticText.Create(AccessPage);
  GenLabel.Parent := AccessPage.Surface;
  GenLabel.Top := Pass2Edit.Top + ScaleY(28); GenLabel.Left := 0; GenLabel.Caption := '';
  y := y + ScaleY(80);
  NoLoginCheck := TNewCheckBox.Create(AccessPage);
  NoLoginCheck.Parent := AccessPage.Surface;
  NoLoginCheck.Top := y; NoLoginCheck.Width := AccessPage.SurfaceWidth;
  NoLoginCheck.Caption := CustomMessage('NoLogin');
  NoLoginCheck.OnClick := @NoLoginClick;
  HelpLabel := TNewStaticText.Create(AccessPage);
  HelpLabel.Parent := AccessPage.Surface;
  HelpLabel.Top := y + ScaleY(22); HelpLabel.Left := ScaleX(18); HelpLabel.Width := AccessPage.SurfaceWidth - ScaleX(18);
  HelpLabel.AutoSize := False; HelpLabel.WordWrap := True; HelpLabel.Height := ScaleY(34);
  HelpLabel.Caption := CustomMessage('NoLoginHelp');
  UpdateAccessControls;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  { En silencioso no hay asistente; con parámetros o sin ellos, ver CurStepChanged. }
  Result := (PageID = AccessPage.ID) and WizardSilent();
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = AccessPage.ID then
  begin
    if NoLoginCheck.Checked then Exit;
    if Trim(UserEdit.Text) = '' then begin MsgBox(CustomMessage('NeedUser'), mbError, MB_OK); Result := False; Exit; end;
    if PassEdit.Text = '' then begin MsgBox(CustomMessage('NeedPassword'), mbError, MB_OK); Result := False; Exit; end;
    if PassEdit.Text <> Pass2Edit.Text then begin MsgBox(CustomMessage('Mismatch'), mbError, MB_OK); Result := False; Exit; end;
  end;
end;

{ Valor entre comillas dobles: launcher.py las quita; así una contraseña con # o comillas se conserva tal cual. }
function EnvLine(key, value: String): String;
begin
  Result := key + '="' + value + '"';
end;

procedure WriteEnv(user, password: String);
var
  lines: TArrayOfString;
begin
  ForceDirectories(ExtractFileDir(EnvPath));
  if user = '' then
  begin
    SetArrayLength(lines, 1);
    lines[0] := '# Checkpoint sin usuario ni contraseña: solo se puede abrir desde este equipo (127.0.0.1).';
  end else
  begin
    SetArrayLength(lines, 3);
    lines[0] := '# Credenciales de Checkpoint (en claro). Bórralas para arrancar sin login en 127.0.0.1.';
    lines[1] := EnvLine('CHECKPOINT_USER', user);
    lines[2] := EnvLine('CHECKPOINT_PASSWORD', password);
  end;
  SaveStringsToUTF8File(EnvPath, lines, False);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep <> ssPostInstall then Exit;
  if WizardSilent() then
  begin
    if ExpandConstant('{param:NOLOGIN|0}') = '1' then
      WriteEnv('', '')
    else if ExpandConstant('{param:CPUSER|}') <> '' then
      WriteEnv(ExpandConstant('{param:CPUSER}'), ExpandConstant('{param:CPPASSWORD|}'))
    else if not FileExists(EnvPath) then
      WriteEnv('', '');
  end else
  begin
    if NoLoginCheck.Checked then WriteEnv('', '')
    else WriteEnv(Trim(UserEdit.Text), PassEdit.Text);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    if (not UninstallSilent()) and (MsgBox(CustomMessage('DeleteData'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES) then
      DelTree(ExpandConstant('{userappdata}\checkpoint'), True, True, True);
end;
