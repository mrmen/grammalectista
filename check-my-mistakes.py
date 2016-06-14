#!python3

import clipboard

import sys
import os.path
import argparse
import json

import grammalecte.fr as gce
import grammalecte.fr.lexicographe as lxg
import grammalecte.fr.textformatter as tf
import grammalecte.text as txt
import grammalecte.tokenizer as tkz
from grammalecte.echo import echo



def generateText (iParagraph, sText, oTokenizer, oDict, bJSON, nWidth=100, bDebug=False, bEmptyIfNoErrors=False):
    aGrammErrs = gce.parse(sText, "FR", bDebug)
    aSpellErrs = []
    for dToken in oTokenizer.genTokens(sText):
        if dToken['sType'] == "WORD" and not oDict.isValidToken(dToken['sValue']):
            aSpellErrs.append(dToken)
    if bEmptyIfNoErrors and not aGrammErrs and not aSpellErrs:
        return ""
    if not bJSON:
        return txt.generateParagraph(sText, aGrammErrs, aSpellErrs, nWidth)
    return "  " + json.dumps({ "iParagraph": iParagraph, "lGrammarErrors": aGrammErrs, "lSpellingErrors": aSpellErrs }, ensure_ascii=False)


def readfile (spf):
    if os.path.isfile(spf):
        with open(spf, "r", encoding="utf-8") as hSrc:
            for sText in hSrc:
                yield sText
    else:
        print("# Error: file not found.")


def output (sText, hDst=None):
    if not hDst:
        echo(sText, end="")
    else:
        hDst.write(sText)


def main ():
    xParser = argparse.ArgumentParser()
    xParser.add_argument("-f", "--file", help="parse file (UTF-8 required!) [on Windows, -f is similar to -ff]", type=str)
    xParser.add_argument("-ff", "--file_to_file", help="parse file (UTF-8 required!) and create a result file (*.res.txt)", type=str)
    xParser.add_argument("-j", "--json", help="generate list of errors in JSON", action="store_true")
    xParser.add_argument("-w", "--width", help="width in characters (40 < width < 200; default: 100)", type=int, choices=range(40,201,10), default=100)
    xParser.add_argument("-tf", "--textformatter", help="auto-format text according to typographical rules", action="store_true")
    xParser.add_argument("-tfo", "--textformatteronly", help="auto-format text and disable grammar checking (only with option 'file' or 'file_to_file')", action="store_true")
    xArgs = xParser.parse_args()

    gce.load()
    gce.setOptions({"html": True})
    echo("Grammalecte v{}".format(gce.version))
    oDict = gce.getDictionary()
    oTokenizer = tkz.Tokenizer("fr")
    oLexGraphe = lxg.Lexicographe(oDict)
    if xArgs.textformatter or xArgs.textformatteronly:
        oTF = tf.TextFormatter()

    sFile = xArgs.file or xArgs.file_to_file
    if sFile:
        # file processing
        hDst = open(sFile[:sFile.rfind(".")]+".res.txt", "w", encoding="utf-8")  if xArgs.file_to_file or sys.platform == "win32"  else None
        bComma = False
        if xArgs.json:
            output('{ "grammalecte": "'+gce.version+'", "lang": "'+gce.lang+'", "data" : [\n', hDst)
        for i, sText in enumerate(readfile(sFile), 1):
            if xArgs.textformatter or xArgs.textformatteronly:
                sText = oTF.formatText(sText)
            if xArgs.textformatteronly:
                output(sText, hDst)
            else:
                sText = generateText(i, sText, oTokenizer, oDict, xArgs.json, nWidth=xArgs.width)
                if sText:
                    if xArgs.json and bComma:
                        output(",\n", hDst)
                    output(sText, hDst)
                    bComma = True
            if hDst:
                echo("§ %d\r" % i, end="", flush=True)
        if xArgs.json:
            output("\n]}\n", hDst)
    else:
        # pseudo-console
        sText = clipboard.get()
        bDebug = False
        for sParagraph in txt.getParagraph(sText):
            if xArgs.textformatter:
                sText = oTF.formatText(sText)
            sRes = generateText(0, sText, oTokenizer, oDict, xArgs.json, nWidth=xArgs.width, bDebug=bDebug, bEmptyIfNoErrors=True)
            if sRes:
                clipboard.set(sRes)
            else:
                clipboard.set("No errors found.")

if __name__ == '__main__':
    main()
