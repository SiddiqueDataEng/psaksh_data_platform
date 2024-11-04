"""Upload corrected .htaccess to fix PassengerAppRoot path."""
import ftplib
import io

ftp = ftplib.FTP()
ftp.connect("ftp.sattioes.com.pk", 21, timeout=30)
ftp.login("publichealth@softcomputech.com", "sattioe1_publichealth")
ftp.set_pasv(True)

content = (
    "# DO NOT REMOVE OR MODIFY. CLOUDLINUX ENV VARS CONFIGURATION BEGIN\n"
    "<IfModule Litespeed>\n"
    "</IfModule>\n"
    "# DO NOT REMOVE OR MODIFY. CLOUDLINUX ENV VARS CONFIGURATION END\n"
    "\n"
    "# DO NOT REMOVE. CLOUDLINUX PASSENGER CONFIGURATION BEGIN\n"
    'PassengerAppRoot "/home/sattioe1/softcomputech.com/publichealth"\n'
    'PassengerBaseURI "/publichealth"\n'
    'PassengerPython "/home/sattioe1/virtualenv/publichealth/3.11/bin/python"\n'
    "# DO NOT REMOVE. CLOUDLINUX PASSENGER CONFIGURATION END\n"
)

data = content.encode("utf-8")
ftp.storbinary("STOR /.htaccess", io.BytesIO(data))
print("Uploaded .htaccess (" + str(len(data)) + " bytes)")

buf = io.BytesIO()
ftp.retrbinary("RETR /.htaccess", buf.write)
print("\n=== Verified on server ===")
print(buf.getvalue().decode())

ftp.quit()
