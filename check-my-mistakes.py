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

def main ():
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
