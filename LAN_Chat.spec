# LAN_Chat.spec — PyInstaller 打包配置（体积优化版）
# 用法: pyinstaller LAN_Chat.spec

# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['lan_chat_pro.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'PIL', 'PIL.Image', 'PIL.ImageTk',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    upx_exclude=[
        '*python312.dll',  # UPX 压缩 python DLL 会导致 "failed to load python dll"
        '*tk*.dll',
        '*tcl*.dll',
        '*vcruntime*.dll',
        '*ucrtbase.dll',
        '*api-ms-win-*',
    ],
    excludes=[
        # 用不到的 PIL 功能模块（保留全部图片格式插件，必须能显示 png/jpg）
        'PIL.ImageDraw', 'PIL.ImageFilter', 'PIL.ImageEnhance',
        'PIL.ImageOps', 'PIL.ImageChops', 'PIL.ImageSequence',
        'PIL.ImageFont', 'PIL.ImageGrab', 'PIL.ImageQt',
        'PIL.ImageShow', 'PIL.ImageStat', 'PIL.ImageTransform',
        'PIL.ImageColor', 'PIL.ImageMode', 'PIL.ImagePath',
        'PIL.ImagePalette', 'PIL.PyAccess', 'PIL.TarIO',
        'PIL.ExifTags', 'PIL.Features', 'PIL._binary',
        'PIL._imagingft', 'PIL._tkinter_finder', 'PIL.PdfParser',
        'PIL.BufrStubImagePlugin', 'PIL.FitsStubImagePlugin',
        'PIL.FpxImagePlugin', 'PIL.GribStubImagePlugin',
        'PIL.Hdf5StubImagePlugin', 'PIL.IcnsImagePlugin',
        'PIL.ImImagePlugin', 'PIL.ImtImagePlugin', 'PIL.MicImagePlugin',
        'PIL.MpegImagePlugin', 'PIL.MspImagePlugin', 'PIL.PcdImagePlugin',
        'PIL.PcxImagePlugin', 'PIL.PdfImagePlugin', 'PIL.PixarImagePlugin',
        'PIL.PpmImagePlugin', 'PIL.PsdImagePlugin', 'PIL.SgiImagePlugin',
        'PIL.SpiderImagePlugin', 'PIL.TgaImagePlugin', 'PIL.TiffImagePlugin',
        'PIL.WebPImagePlugin', 'PIL.WmfImagePlugin', 'PIL.XbmImagePlugin',
        'PIL.XpmImagePlugin', 'PIL.Jpeg2KImagePlugin',
        # 用不到的 Python 标准库（tkinter 及其子模块必须保留）
        'unittest', 'pydoc', 'doctest', 'pdb', 'tkinter.test',
        'test', 'distutils', 'venv', 'ensurepip', 'lib2to3',
        'sqlite3', 'turtle', 'turtledemo', 'xmlrpc', 'imaplib',
        'poplib', 'smtplib', 'telnetlib', 'nntplib', 'ftplib',
        'wsgiref', 'http.cookiejar', 'http.cookies',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='LAN_Chat',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,          # 去掉符号表
    upx=False,           # UPX 压缩 python DLL 会损坏导致无法启动，关闭
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
