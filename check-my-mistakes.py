#!python3

import clipboard
import webbrowser

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
    oDict = gce.getDictionary()
    oTokenizer = tkz.Tokenizer("fr")
    oLexGraphe = lxg.Lexicographe(oDict)
    if xArgs.textformatter or xArgs.textformatteronly:
        oTF = tf.TextFormatter()

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
    print(sRes)

if __name__ == '__main__':
    main()
    webbrowser.open('workflow://run-workflow?name=my-look')