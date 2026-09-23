# headless stub: ePub3-itizer only uses QApplication + QFileDialog.getSaveFileName
import os
class QApplication:
    def __init__(self,*a,**k): pass
    def quit(self): pass
    @staticmethod
    def instance(): return None
class QFileDialog:
    @staticmethod
    def getSaveFileName(*a,**k): return (os.environ['EPUB3_OUT'],'')
def __getattr__(name): return type(name,(),{'__init__':lambda self,*a,**k:None})
