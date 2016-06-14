# -*- encoding: UTF-8 -*-

import re
import sys
import os
import traceback

from ..ibdawg import IBDAWG
from ..echo import echo
from . import gc_options


__all__ = [ "lang", "locales", "pkg", "name", "version", "author", \
            "load", "parse", "getDictionary", \
            "setOptions", "getOptions", "getOptionsLabels", "resetOptions", \
            "ignoreRule", "resetIgnoreRules" ]

__version__ = u"0.5.6"


lang = u"fr"
locales = {'fr-LU': ['fr', 'LU', ''], 'fr-CA': ['fr', 'CA', ''], 'fr-BE': ['fr', 'BE', ''], 'fr-FR': ['fr', 'FR', ''], 'fr-CH': ['fr', 'CH', ''], 'fr-MC': ['fr', 'MC', '']}
pkg = u"grammalecte"
name = u"Grammalecte"
version = u"0.5.6"
author = u"Olivier R."

# commons regexes
_zEndOfSentence = re.compile(u'([.?!:;…][ .?!… »”")]*|.$)')
_zBeginOfParagraph = re.compile(u"^\W*")
_zEndOfParagraph = re.compile(u"\W*$")
_zNextWord = re.compile(u" +(\w[\w-]*)")
_zPrevWord = re.compile(u"(\w[\w-]*) +$")

# grammar rules and dictionary
_rules = None
_dOptions = dict(gc_options.dOpt)       # duplication necessary, to be able to reset to default
_aIgnoredRules = set()
_oDict = None
_dAnalyses = {}                         # cache for data from dictionary

_GLOBALS = globals()


#### Parsing

def parse (sText, sCountry="FR", bDebug=False, dOptions=None):
    "analyses the paragraph sText and returns list of errors"
    aErrors = None
    sAlt = sText
    dDA = {}
    dOpt = _dOptions  if not dOptions  else dOptions

    # parse paragraph
    try:
        sNew, aErrors = _proofread(sText, sAlt, 0, True, dDA, sCountry, dOpt, bDebug)
        if sNew:
            sText = sNew
    except:
        raise

    # parse sentences
    for iStart, iEnd in _getSentenceBoundaries(sText):
        if 4 < (iEnd - iStart) < 2000:
            dDA.clear()
            try:
                _, errs = _proofread(sText[iStart:iEnd], sAlt[iStart:iEnd], iStart, False, dDA, sCountry, dOpt, bDebug)
                aErrors.extend(errs)
            except:
                raise
    return aErrors


def _getSentenceBoundaries (sText):
    iStart = _zBeginOfParagraph.match(sText).end()
    for m in _zEndOfSentence.finditer(sText):
        yield (iStart, m.end())
        iStart = m.end()


def _proofread (s, sx, nOffset, bParagraph, dDA, sCountry, dOptions, bDebug):
    aErrs = []
    bChange = False
    
    if not bParagraph:
        # after the first pass, we modify automatically some characters
        if u" " in s:
            s = s.replace(u" ", u' ') # nbsp
            bChange = True
        if u" " in s:
            s = s.replace(u" ", u' ') # nnbsp
            bChange = True
        if u"@" in s:
            s = s.replace(u"@", u' ')
            bChange = True
        if u"'" in s:
            s = s.replace(u"'", u"’")
            bChange = True
        if u"‑" in s:
            s = s.replace(u"‑", u"-") # nobreakdash
            bChange = True

    bIdRule = option('idrule')

    for sOption, zRegex, bUppercase, sRuleId, lActions in _getRules(bParagraph):
        if (not sOption or dOptions.get(sOption, False)) and not sRuleId in _aIgnoredRules:
            for m in zRegex.finditer(s):
                for sFuncCond, cActionType, sWhat, *eAct in lActions:
                # action in lActions: [ condition, action type, replacement/suggestion/action[, iGroup[, message, URL]] ]
                    try:
                        if not sFuncCond or _GLOBALS[sFuncCond](s, sx, m, dDA, sCountry):
                            if cActionType == "-":
                                # grammar error
                                # (text, replacement, nOffset, m, iGroup, sId, bUppercase, sURL, bIdRule)
                                aErrs.append(_createError(s, sWhat, nOffset, m, eAct[0], sRuleId, bUppercase, eAct[1], eAct[2], bIdRule, sOption))
                            elif cActionType == "~":
                                # text processor
                                s = _rewrite(s, sWhat, eAct[0], m, bUppercase)
                                bChange = True
                                if bDebug:
                                    echo(u"~ " + s + "  -- " + m.group(eAct[0]) + "  # " + sRuleId)
                            elif cActionType == "=":
                                # disambiguation
                                _GLOBALS[sWhat](s, m, dDA)
                                if bDebug:
                                    echo(u"= " + m.group(0) + "  # " + sRuleId + "\nDA: " + str(dDA))
                            else:
                                echo("# error: unknown action at " + sRuleId)
                    except Exception as e:
                        raise Exception(str(e), sRuleId)
    if bChange:
        return (s, aErrs)
    return (False, aErrs)


def _createWriterError (s, sRepl, nOffset, m, iGroup, sId, bUppercase, sMsg, sURL, bIdRule, sOption):
    "error for Writer (LO/OO)"
    xErr = SingleProofreadingError()
    #xErr = uno.createUnoStruct( "com.sun.star.linguistic2.SingleProofreadingError" )
    xErr.nErrorStart        = nOffset + m.start(iGroup)
    xErr.nErrorLength       = m.end(iGroup) - m.start(iGroup)
    xErr.nErrorType         = PROOFREADING
    xErr.aRuleIdentifier    = sId
    # suggestions
    if sRepl[0:1] == "=":
        sugg = _GLOBALS[sRepl[1:]](s, m)
        if sugg:
            if bUppercase and m.group(iGroup)[0:1].isupper():
                xErr.aSuggestions = tuple(map(str.capitalize, sugg.split("|")))
            else:
                xErr.aSuggestions = tuple(sugg.split("|"))
        else:
            xErr.aSuggestions = ()
    elif sRepl == "_":
        xErr.aSuggestions = ()
    else:
        if bUppercase and m.group(iGroup)[0:1].isupper():
            xErr.aSuggestions = tuple(map(str.capitalize, m.expand(sRepl).split("|")))
        else:
            xErr.aSuggestions = tuple(m.expand(sRepl).split("|"))
    # Message
    if sMsg[0:1] == "=":
        sMessage = _GLOBALS[sMsg[1:]](s, m)
    else:
        sMessage = m.expand(sMsg)
    xErr.aShortComment      = sMessage   # sMessage.split("|")[0]     # in context menu
    xErr.aFullComment       = sMessage   # sMessage.split("|")[-1]    # in dialog
    if bIdRule:
        xErr.aShortComment += "  # " + sId
    # URL
    if sURL:
        p = PropertyValue()
        p.Name = "FullCommentURL"
        p.Value = sURL
        xErr.aProperties    = (p,)
    else:
        xErr.aProperties    = ()
    return xErr


def _createDictError (s, sRepl, nOffset, m, iGroup, sId, bUppercase, sMsg, sURL, bIdRule, sOption):
    "error as a dictionary"
    dErr = {}
    dErr["nStart"]          = nOffset + m.start(iGroup)
    dErr["nEnd"]            = nOffset + m.end(iGroup)
    dErr["sRuleId"]         = sId
    dErr["sType"]           = sOption  if sOption  else "notype"
    # suggestions
    if sRepl[0:1] == "=":
        sugg = _GLOBALS[sRepl[1:]](s, m)
        if sugg:
            if bUppercase and m.group(iGroup)[0:1].isupper():
                dErr["aSuggestions"] = list(map(str.capitalize, sugg.split("|")))
            else:
                dErr["aSuggestions"] = sugg.split("|")
        else:
            dErr["aSuggestions"] = ()
    elif sRepl == "_":
        dErr["aSuggestions"] = ()
    else:
        if bUppercase and m.group(iGroup)[0:1].isupper():
            dErr["aSuggestions"] = list(map(str.capitalize, m.expand(sRepl).split("|")))
        else:
            dErr["aSuggestions"] = m.expand(sRepl).split("|")
    # Message
    if sMsg[0:1] == "=":
        sMessage = _GLOBALS[sMsg[1:]](s, m)
    else:
        sMessage = m.expand(sMsg)
    dErr["sMessage"]      = sMessage
    if bIdRule:
        dErr["sMessage"] += "  # " + sId
    # URL
    dErr["URL"] = sURL  if sURL  else ""
    return dErr


def _rewrite (s, sRepl, iGroup, m, bUppercase):
    "text processor: write sRepl in s at iGroup position"
    ln = m.end(iGroup) - m.start(iGroup)
    if sRepl == "*":
        sNew = " " * ln
    elif sRepl == ">" or sRepl == "_" or sRepl == u"~":
        sNew = sRepl + " " * (ln-1)
    elif sRepl == "@":
        sNew = "@" * ln
    elif sRepl[0:1] == "=":
        if sRepl[1:2] != "@":
            sNew = _GLOBALS[sRepl[1:]](s, m)
            sNew = sNew + " " * (ln-len(sNew))
        else:
            sNew = _GLOBALS[sRepl[2:]](s, m)
            sNew = sNew + "@" * (ln-len(sNew))
        if bUppercase and m.group(iGroup)[0:1].isupper():
            sNew = sNew.capitalize()
    else:
        sNew = m.expand(sRepl)
        sNew = sNew + " " * (ln-len(sNew))
    return s[0:m.start(iGroup)] + sNew + s[m.end(iGroup):]


def ignoreRule (sId):
    _aIgnoredRules.add(sId)


def resetIgnoreRules ():
    _aIgnoredRules.clear()


#### init

try:
    # LibreOffice / OpenOffice
    from com.sun.star.linguistic2 import SingleProofreadingError
    from com.sun.star.text.TextMarkupType import PROOFREADING
    from com.sun.star.beans import PropertyValue
    #import lightproof_handler_grammalecte as opt
    _createError = _createWriterError
except ImportError:
    _createError = _createDictError


def load ():
    global _oDict
    try:
        _oDict = IBDAWG("french.bdic")
    except:
        traceback.print_exc()


def setOptions (dOpt):
    _dOptions.update(dOpt)


def getOptions ():
    return _dOptions


def getOptionsLabels (sLang):
    return gc_options.getUI(sLang)


def resetOptions ():
    global _dOptions
    _dOptions = dict(gc_options.dOpt)


def getDictionary ():
    return _oDict


def _getRules (bParagraph):
    try:
        if not bParagraph:
            return _rules.lSentenceRules
        return _rules.lParagraphRules
    except:
        _loadRules()
    if not bParagraph:
        return _rules.lSentenceRules
    return _rules.lParagraphRules


def _loadRules ():
    from itertools import chain
    from . import gc_rules
    global _rules
    _rules = gc_rules
    # compile rules regex
    for rule in chain(_rules.lParagraphRules, _rules.lSentenceRules):
        try:
            rule[1] = re.compile(rule[1])
        except:
            echo("Bad regular expression in # " + str(rule[3]))
            rule[1] = "(?i)<Grammalecte>"


def _getPath ():
    return os.path.join(os.path.dirname(sys.modules[__name__].__file__), __name__ + ".py")



#### common functions

def option (sOpt):
    "return True if option sOpt is active"
    return _dOptions.get(sOpt, False)


def displayInfo (dDA, tWord):
    "for debugging: retrieve info of word"
    if not tWord:
        echo("> nothing to find")
        return True
    if tWord[1] not in _dAnalyses and not _storeMorphFromFSA(tWord[1]):
        echo("> not in FSA")
        return True
    if tWord[0] in dDA:
        echo("DA: " + str(dDA[tWord[0]]))
    echo("FSA: " + str(_dAnalyses[tWord[1]]))
    return True


def _storeMorphFromFSA (sWord):
    "retrieves morphologies list from _oDict -> _dAnalyses"
    global _dAnalyses
    _dAnalyses[sWord] = _oDict.getMorph(sWord)
    return True  if _dAnalyses[sWord]  else False


def morph (dDA, tWord, sPattern, bStrict=True, bNoWord=False):
    "analyse a tuple (position, word), return True if sPattern in morphologies (disambiguation on)"
    if not tWord:
        return bNoWord
    if tWord[1] not in _dAnalyses and not _storeMorphFromFSA(tWord[1]):
        return False
    lMorph = dDA[tWord[0]]  if tWord[0] in dDA  else _dAnalyses[tWord[1]]
    if not lMorph:
        return False
    p = re.compile(sPattern)
    if bStrict:
        return all(p.search(s)  for s in lMorph)
    return any(p.search(s)  for s in lMorph)


def morphex (dDA, tWord, sPattern, sNegPattern, bNoWord=False):
    "analyse a tuple (position, word), returns True if not sNegPattern in word morphologies and sPattern in word morphologies (disambiguation on)"
    if not tWord:
        return bNoWord
    if tWord[1] not in _dAnalyses and not _storeMorphFromFSA(tWord[1]):
        return False
    lMorph = dDA[tWord[0]]  if tWord[0] in dDA  else _dAnalyses[tWord[1]]
    # check negative condition
    np = re.compile(sNegPattern)
    if any(np.search(s)  for s in lMorph):
        return False
    # search sPattern
    p = re.compile(sPattern)
    return any(p.search(s)  for s in lMorph)


def analyse (sWord, sPattern, bStrict=True):
    "analyse a word, return True if sPattern in morphologies (disambiguation off)"
    if sWord not in _dAnalyses and not _storeMorphFromFSA(sWord):
        return False
    if not _dAnalyses[sWord]:
        return False
    p = re.compile(sPattern)
    if bStrict:
        return all(p.search(s)  for s in _dAnalyses[sWord])
    return any(p.search(s)  for s in _dAnalyses[sWord])


def analysex (sWord, sPattern, sNegPattern):
    "analyse a word, returns True if not sNegPattern in word morphologies and sPattern in word morphologies (disambiguation off)"
    if sWord not in _dAnalyses and not _storeMorphFromFSA(sWord):
        return False
    # check negative condition
    np = re.compile(sNegPattern)
    if any(np.search(s)  for s in _dAnalyses[sWord]):
        return False
    # search sPattern
    p = re.compile(sPattern)
    return any(p.search(s)  for s in _dAnalyses[sWord])


def stem (sWord):
    "returns a list of sWord's stems"
    if not sWord:
        return []
    if sWord not in _dAnalyses and not _storeMorphFromFSA(sWord):
        return []
    return [ s[1:s.find(" ")]  for s in _dAnalyses[sWord] ]


## functions to get text outside pattern scope

# warning: check compile_rules.py to understand how it works

def nextword (s, iStart, n):
    "get the nth word of the input string or empty string"
    m = re.match(u"( +[\\w%-]+){" + str(n-1) + u"} +([\\w%-]+)", s[iStart:])
    if not m:
        return None
    return (iStart+m.start(2), m.group(2))


def prevword (s, iEnd, n):
    "get the (-)nth word of the input string or empty string"
    m = re.search(u"([\\w%-]+) +([\\w%-]+ +){" + str(n-1) + u"}$", s[:iEnd])
    if not m:
        return None
    return (m.start(1), m.group(1))


def nextword1 (s, iStart):
    "get next word (optimization)"
    m = _zNextWord.match(s[iStart:])
    if not m:
        return None
    return (iStart+m.start(1), m.group(1))


def prevword1 (s, iEnd):
    "get previous word (optimization)"
    m = _zPrevWord.search(s[:iEnd])
    if not m:
        return None
    return (m.start(1), m.group(1))


def look (s, sPattern, sNegPattern=None):
    "seek sPattern in s (before/after/fulltext), if sNegPattern not in s"
    if sNegPattern and re.search(sNegPattern, s):
        return False
    if re.search(sPattern, s):
        return True
    return False


def look_chk1 (dDA, s, nOffset, sPattern, sPatternGroup1, sNegPatternGroup1=None):
    "returns True if s has pattern sPattern and m.group(1) has pattern sPatternGroup1"
    m = re.search(sPattern, s)
    if not m:
        return False
    try:
        sWord = m.group(1)
        nPos = m.start(1) + nOffset
    except:
        #print("Missing group 1")
        return False
    if sNegPatternGroup1:
        return morphex(dDA, (nPos, sWord), sPatternGroup1, sNegPatternGroup1)
    return morph(dDA, (nPos, sWord), sPatternGroup1, False)


#### Disambiguator

def select (dDA, nPos, sWord, sPattern, lDefault=None):
    if not sWord:
        return True
    if nPos in dDA:
        return True
    if sWord not in _dAnalyses and not _storeMorphFromFSA(sWord):
        return True
    if len(_dAnalyses[sWord]) == 1:
        return True
    lSelect = [ sMorph  for sMorph in _dAnalyses[sWord]  if re.search(sPattern, sMorph) ]
    if lSelect:
        if len(lSelect) != len(_dAnalyses[sWord]):
            dDA[nPos] = lSelect
            #echo("= "+sWord+" "+str(dDA.get(nPos, "null")))
    elif lDefault:
        dDA[nPos] = lDefault
        #echo("= "+sWord+" "+str(dDA.get(nPos, "null")))
    return True


def exclude (dDA, nPos, sWord, sPattern, lDefault=None):
    if not sWord:
        return True
    if nPos in dDA:
        return True
    if sWord not in _dAnalyses and not _storeMorphFromFSA(sWord):
        return True
    if len(_dAnalyses[sWord]) == 1:
        return True
    lSelect = [ sMorph  for sMorph in _dAnalyses[sWord]  if not re.search(sPattern, sMorph) ]
    if lSelect:
        if len(lSelect) != len(_dAnalyses[sWord]):
            dDA[nPos] = lSelect
            #echo("= "+sWord+" "+str(dDA.get(nPos, "null")))
    elif lDefault:
        dDA[nPos] = lDefault
        #echo("= "+sWord+" "+str(dDA.get(nPos, "null")))
    return True


def define (dDA, nPos, lMorph):
    dDA[nPos] = lMorph
    #echo("= "+str(nPos)+" "+str(dDA[nPos]))
    return True


#### GRAMMAR CHECKER PLUGINS



#### GRAMMAR CHECKING ENGINE PLUGIN: Parsing functions for French language

from . import cregex as cr


def rewriteSubject (s1, s2):
    # s1 is supposed to be prn/patr/npr (M[12P])
    if s2 == "lui":
        return "ils"
    if s2 == "moi":
        return "nous"
    if s2 == "toi":
        return "vous"
    if s2 == "nous":
        return "nous"
    if s2 == "vous":
        return "vous"
    if s2 == "eux":
        return "ils"
    if s2 == "elle" or s2 == "elles":
        # We don’t check if word exists in _dAnalyses, for it is assumed it has been done before
        if cr.mbNprMasNotFem(_dAnalyses.get(s1, False)):
            return "ils"
        # si épicène, indéterminable, mais OSEF, le féminin l’emporte
        return "elles"
    return s1 + " et " + s2


def apposition (sWord1, sWord2):
    "returns True if nom + nom (no agreement required)"
    # We don’t check if word exists in _dAnalyses, for it is assumed it has been done before
    return cr.mbNomNotAdj(_dAnalyses.get(sWord2, False)) and cr.mbPpasNomNotAdj(_dAnalyses.get(sWord1, False))


def isAmbiguousNAV (sWord):
    "words which are nom|adj and verb are ambiguous (except être and avoir)"
    if sWord not in _dAnalyses and not _storeMorphFromFSA(sWord):
        return False
    if not cr.mbNomAdj(_dAnalyses[sWord]) or sWord == "est":
        return False
    if cr.mbVconj(_dAnalyses[sWord]) and not cr.mbMG(_dAnalyses[sWord]):
        return True
    return False


def isAmbiguousAndWrong (sWord1, sWord2, sReqMorphNA, sReqMorphConj):
    "use it if sWord1 won’t be a verb; word2 is assumed to be True via isAmbiguousNAV"
    # We don’t check if word exists in _dAnalyses, for it is assumed it has been done before
    a2 = _dAnalyses.get(sWord2, None)
    if not a2:
        return False
    if cr.checkConjVerb(a2, sReqMorphConj):
        # verb word2 is ok
        return False
    a1 = _dAnalyses.get(sWord1, None)
    if not a1:
        return False
    if cr.checkAgreement(a1, a2) and (cr.mbAdj(a2) or cr.mbAdj(a1)):
        return False
    return True


def isVeryAmbiguousAndWrong (sWord1, sWord2, sReqMorphNA, sReqMorphConj, bLastHopeCond):
    "use it if sWord1 can be also a verb; word2 is assumed to be True via isAmbiguousNAV"
    # We don’t check if word exists in _dAnalyses, for it is assumed it has been done before
    a2 = _dAnalyses.get(sWord2, None)
    if not a2:
        return False
    if cr.checkConjVerb(a2, sReqMorphConj):
        # verb word2 is ok
        return False
    a1 = _dAnalyses.get(sWord1, None)
    if not a1:
        return False
    if cr.checkAgreement(a1, a2) and (cr.mbAdj(a2) or cr.mbAdjNb(a1)):
        return False
    # now, we know there no agreement, and conjugation is also wrong
    if cr.isNomAdj(a1):
        return True
    #if cr.isNomAdjVerb(a1): # considered True
    if bLastHopeCond:
        return True
    return False


def checkAgreement (sWord1, sWord2):
    # We don’t check if word exists in _dAnalyses, for it is assumed it has been done before
    a2 = _dAnalyses.get(sWord2, None)
    if not a2:
        return True
    a1 = _dAnalyses.get(sWord1, None)
    if not a1:
        return True
    return cr.checkAgreement(a1, a2)


_zUnitSpecial = re.compile(u"[µ/⁰¹²³⁴⁵⁶⁷⁸⁹Ωℓ·]")
_zUnitNumbers = re.compile(u"[0-9]")

def mbUnit (s):
    if _zUnitSpecial.search(s):
        return True
    if 1 < len(s) < 16 and s[0:1].islower() and (not s[1:].islower() or _zUnitNumbers.search(s)):
        return True
    return False


#### Syntagmes

_zEndOfNG1 = re.compile(u" +(?:, +|)(?:n(?:’|e |o(?:u?s|tre) )|l(?:’|e(?:urs?|s|) |a )|j(?:’|e )|m(?:’|es? |a |on )|t(?:’|es? |a |u )|s(?:’|es? |a )|c(?:’|e(?:t|tte|s|) )|ç(?:a |’)|ils? |vo(?:u?s|tre) )")
_zEndOfNG2 = re.compile(r" +(\w[\w-]+)")
_zEndOfNG3 = re.compile(r" *, +(\w[\w-]+)")


def isEndOfNG (dDA, s, iOffset):
    if _zEndOfNG1.match(s):
        return True
    m = _zEndOfNG2.match(s)
    if m and morphex(dDA, (iOffset+m.start(1), m.group(1)), ":[VR]", ":[NAQP]"):
        return True
    m = _zEndOfNG3.match(s)
    if m and not morph(dDA, (iOffset+m.start(1), m.group(1)), ":[NA]", False):
        return True
    return False


#### Exceptions

aREGULARPLURAL = frozenset(["abricot", "amarante", "aubergine", "acajou", "anthracite", "brique", "caca", u"café", "carotte", "cerise", "chataigne", "corail", "citron", u"crème", "grave", "groseille", "jonquille", "marron", "olive", "pervenche", "prune", "sable"])
aSHOULDBEVERB = frozenset(["aller", "manger"]) 


#### GRAMMAR CHECKING ENGINE PLUGIN

#### Check date validity

_lDay = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_dMonth = { "janvier":1, u"février":2, "mars":3, "avril":4, "mai":5, "juin":6, "juillet":7, u"août":8, "aout":8, "septembre":9, "octobre":10, "novembre":11, u"décembre":12 }

import datetime

def checkDate (day, month, year):
    "to use if month is a number"
    try:
        return datetime.date(int(year), int(month), int(day))
    except ValueError:
        return False
    except:
        return True

def checkDateWithString (day, month, year):
    "to use if month is a noun"
    try:
        return datetime.date(int(year), _dMonth.get(month.lower(), ""), int(day))
    except ValueError:
        return False
    except:
        return True

def checkDay (weekday, day, month, year):
    "to use if month is a number"
    oDate = checkDate(day, month, year)
    if oDate and _lDay[oDate.weekday()] != weekday.lower():
        return False
    return True
        
def checkDayWithString (weekday, day, month, year):
    "to use if month is a noun"
    oDate = checkDate(day, _dMonth.get(month, ""), year)
    if oDate and _lDay[oDate.weekday()] != weekday.lower():
        return False
    return True

def getDay (day, month, year):
    "to use if month is a number"
    return _lDay[datetime.date(int(year), int(month), int(day)).weekday()]

def getDayWithString (day, month, year):
    "to use if month is a noun"
    return _lDay[datetime.date(int(year), _dMonth.get(month.lower(), ""), int(day)).weekday()]


#### GRAMMAR CHECKING ENGINE PLUGIN: Suggestion mechanisms

from . import conj
from . import mfsp
from . import phonet


## Verbs

def suggVerb (sFlex, sWho, funcSugg2=None):
    aSugg = set()
    for sStem in stem(sFlex):
        tTags = conj._getTags(sStem)
        if tTags:
            # we get the tense
            aTense = set()
            for sMorph in _dAnalyses.get(sFlex, []): # we don’t check if word exists in _dAnalyses, for it is assumed it has been done before
                for m in re.finditer(sStem+" .*?(:(?:Y|I[pqsf]|S[pq]|K|P))", sMorph):
                    # stem must be used in regex to prevent confusion between different verbs (e.g. sauras has 2 stems: savoir and saurer)
                    if m:
                        if m.group(1) == ":Y":
                            aTense.add(":Ip")
                            aTense.add(":Iq")
                            aTense.add(":Is")
                        elif m.group(1) == ":P":
                            aTense.add(":Ip")
                        else:
                            aTense.add(m.group(1))
            for sTense in aTense:
                if sWho == u":1ś" and not conj._hasConjWithTags(tTags, sTense, u":1ś"):
                    sWho = ":1s"
                if conj._hasConjWithTags(tTags, sTense, sWho):
                    aSugg.add(conj._getConjWithTags(sStem, tTags, sTense, sWho))
    if funcSugg2:
        aSugg2 = funcSugg2(sFlex)
        if aSugg2:
            aSugg.add(aSugg2)
    if aSugg:
        return u"|".join(aSugg)
    return ""


def suggVerbPpas (sFlex, sWhat=None):
    aSugg = set()
    for sStem in stem(sFlex):
        tTags = conj._getTags(sStem)
        if tTags:
            if not sWhat:
                aSugg.add(conj._getConjWithTags(sStem, tTags, ":PQ", ":Q1"))
                aSugg.add(conj._getConjWithTags(sStem, tTags, ":PQ", ":Q2"))
                aSugg.add(conj._getConjWithTags(sStem, tTags, ":PQ", ":Q3"))
                aSugg.add(conj._getConjWithTags(sStem, tTags, ":PQ", ":Q4"))
                aSugg.discard("")
            elif sWhat == ":m:s":
                aSugg.add(conj._getConjWithTags(sStem, tTags, ":PQ", ":Q1"))
            elif sWhat == ":m:p":
                if conj._hasConjWithTags(tTags, ":PQ", ":Q2"):
                    aSugg.add(conj._getConjWithTags(sStem, tTags, ":PQ", ":Q2"))
                else:
                    aSugg.add(conj._getConjWithTags(sStem, tTags, ":PQ", ":Q1"))
            elif sWhat == ":f:s":
                if conj._hasConjWithTags(sStem, tTags, ":PQ", ":Q3"):
                    aSugg.add(conj._getConjWithTags(sStem, tTags, ":PQ", ":Q3"))
                else:
                    aSugg.add(conj._getConjWithTags(sStem, tTags, ":PQ", ":Q1"))
            elif sWhat == ":f:p":
                if conj._hasConjWithTags(sStem, tTags, ":PQ", ":Q4"):
                    aSugg.add(conj._getConjWithTags(sStem, tTags, ":PQ", ":Q4"))
                else:
                    aSugg.add(conj._getConjWithTags(sStem, tTags, ":PQ", ":Q1"))
            else:
                aSugg.add(conj._getConjWithTags(sStem, tTags, ":PQ", ":Q1"))
    if aSugg:
        return u"|".join(aSugg)
    return ""


def suggVerbTense (sFlex, sTense, sWho):
    aSugg = set()
    for sStem in stem(sFlex):
        if conj.hasConj(sStem, ":E", sWho):
            aSugg.add(conj.getConj(sStem, ":E", sWho))
    if aSugg:
        return u"|".join(aSugg)
    return ""


def suggVerbImpe (sFlex):
    aSugg = set()
    for sStem in stem(sFlex):
        tTags = conj._getTags(sStem)
        if tTags:
            if conj._hasConjWithTags(tTags, ":E", ":2s"):
                aSugg.add(conj._getConjWithTags(sStem, tTags, ":E", ":2s"))
            if conj._hasConjWithTags(tTags, ":E", ":1p"):
                aSugg.add(conj._getConjWithTags(sStem, tTags, ":E", ":1p"))
            if conj._hasConjWithTags(tTags, ":E", ":2p"):
                aSugg.add(conj._getConjWithTags(sStem, tTags, ":E", ":2p"))
    if aSugg:
        return u"|".join(aSugg)
    return ""


def suggVerbInfi (sFlex):
    return u"|".join(stem(sFlex))


_dQuiEst = { "je": ":1s", u"j’": ":1s", u"j’en": ":1s", u"j’y": ":1s", \
             "tu": ":2s", "il": ":3s", "on": ":3s", "elle": ":3s", "nous": ":1p", "vous": ":2p", "ils": ":3p", "elles": ":3p" }
_lIndicatif = [":Ip", ":Iq", ":Is", ":If"]
_lSubjonctif = [":Sp", ":Sq"]

def suggVerbMode (sFlex, cMode, sSuj):
    if cMode == ":I":
        lMode = _lIndicatif
    elif cMode == ":S":
        lMode = _lSubjonctif
    elif cMode.startswith((":I", ":S")):
        lMode = [cMode]
    else:
        return ""
    sWho = _dQuiEst.get(sSuj.lower(), None)
    if not sWho:
        if sSuj[0:1].islower(): # pas un pronom, ni un nom propre
            return ""
        sWho = ":3s"
    aSugg = set()
    for sStem in stem(sFlex):
        tTags = conj._getTags(sStem)
        if tTags:
            for sTense in lMode:
                if conj._hasConjWithTags(tTags, sTense, sWho):
                    aSugg.add(conj._getConjWithTags(sStem, tTags, sTense, sWho))
    if aSugg:
        return u"|".join(aSugg)
    return ""


## Nouns and adjectives

def suggPlur (sFlex, sWordToAgree=None):
    "returns plural forms assuming sFlex is singular"
    if sWordToAgree:
        if sWordToAgree not in _dAnalyses and not _storeMorphFromFSA(sWordToAgree):
            return ""
        sGender = cr.getGender(_dAnalyses.get(sWordToAgree, []))
        if sGender == ":m":
            return suggMasPlur(sFlex)
        elif sGender == ":f":
            return suggFemPlur(sFlex)
    aSugg = set()
    if "-" not in sFlex:
        if sFlex.endswith("l"):
            if sFlex.endswith("al") and len(sFlex) > 2 and _oDict.isValid(sFlex[:-1]+"ux"):
                aSugg.add(sFlex[:-1]+"ux")
            if sFlex.endswith("ail") and len(sFlex) > 3 and _oDict.isValid(sFlex[:-2]+"ux"):
                aSugg.add(sFlex[:-2]+"ux")
        if _oDict.isValid(sFlex+"s"):
            aSugg.add(sFlex+"s")
        if _oDict.isValid(sFlex+"x"):
            aSugg.add(sFlex+"x")
    if mfsp.hasMiscPlural(sFlex):
        aSugg.update(mfsp.getMiscPlural(sFlex))
    if aSugg:
        return u"|".join(aSugg)
    return ""


def suggSing (sFlex):
    "returns singular forms assuming sFlex is plural"
    if "-" in sFlex:
        return ""
    aSugg = set()
    if sFlex.endswith("ux"):
        if _oDict.isValid(sFlex[:-2]+"l"):
            aSugg.add(sFlex[:-2]+"l")
        if _oDict.isValid(sFlex[:-2]+"il"):
            aSugg.add(sFlex[:-2]+"il")
    if _oDict.isValid(sFlex[:-1]):
        aSugg.add(sFlex[:-1])
    if aSugg:
        return u"|".join(aSugg)
    return ""


def suggMasSing (sFlex):
    "returns masculine singular forms"
    # we don’t check if word exists in _dAnalyses, for it is assumed it has been done before
    aSugg = set()
    for sMorph in _dAnalyses.get(sFlex, []):
        if not ":V" in sMorph:
            # not a verb
            if ":m" in sMorph or ":e" in sMorph:
                aSugg.add(suggSing(sFlex))
            else:
                sStem = cr.getLemmaOfMorph(sMorph)
                if mfsp.isFemForm(sStem):
                    aSugg.update(mfsp.getMasForm(sStem, False))
        else:
            # a verb
            sVerb = cr.getLemmaOfMorph(sMorph)
            if conj.hasConj(sVerb, ":PQ", ":Q1"):
                aSugg.add(conj.getConj(sVerb, ":PQ", ":Q1"))
    if aSugg:
        return u"|".join(aSugg)
    return ""


def suggMasPlur (sFlex):
    "returns masculine plural forms"
    # we don’t check if word exists in _dAnalyses, for it is assumed it has been done before
    aSugg = set()
    for sMorph in _dAnalyses.get(sFlex, []):
        if not ":V" in sMorph:
            # not a verb
            if ":m" in sMorph or ":e" in sMorph:
                aSugg.add(suggPlur(sFlex))
            else:
                sStem = cr.getLemmaOfMorph(sMorph)
                if mfsp.isFemForm(sStem):
                    aSugg.update(mfsp.getMasForm(sStem, True))
        else:
            # a verb
            sVerb = cr.getLemmaOfMorph(sMorph)
            if conj.hasConj(sVerb, ":PQ", ":Q2"):
                aSugg.add(conj.getConj(sVerb, ":PQ", ":Q2"))
            elif conj.hasConj(sVerb, ":PQ", ":Q1"):
                aSugg.add(conj.getConj(sVerb, ":PQ", ":Q1"))
    if aSugg:
        return u"|".join(aSugg)
    return ""


def suggFemSing (sFlex):
    "returns feminine singular forms"
    # we don’t check if word exists in _dAnalyses, for it is assumed it has been done before
    aSugg = set()
    for sMorph in _dAnalyses.get(sFlex, []):
        if not ":V" in sMorph:
            # not a verb
            if ":f" in sMorph or ":e" in sMorph:
                aSugg.add(suggSing(sFlex))
            else:
                sStem = cr.getLemmaOfMorph(sMorph)
                if mfsp.isFemForm(sStem):
                    aSugg.add(sStem)
        else:
            # a verb
            sVerb = cr.getLemmaOfMorph(sMorph)
            if conj.hasConj(sVerb, ":PQ", ":Q3"):
                aSugg.add(conj.getConj(sVerb, ":PQ", ":Q3"))
    if aSugg:
        return u"|".join(aSugg)
    return ""


def suggFemPlur (sFlex):
    "returns feminine plural forms"
    # we don’t check if word exists in _dAnalyses, for it is assumed it has been done before
    aSugg = set()
    for sMorph in _dAnalyses.get(sFlex, []):
        if not ":V" in sMorph:
            # not a verb
            if ":f" in sMorph or ":e" in sMorph:
                aSugg.add(suggPlur(sFlex))
            else:
                sStem = cr.getLemmaOfMorph(sMorph)
                if mfsp.isFemForm(sStem):
                    aSugg.add(sStem+"s")
        else:
            # a verb
            sVerb = cr.getLemmaOfMorph(sMorph)
            if conj.hasConj(sVerb, ":PQ", ":Q4"):
                aSugg.add(conj.getConj(sVerb, ":PQ", ":Q4"))
    if aSugg:
        return u"|".join(aSugg)
    return ""


def switchGender (sFlex, bPlur=None):
    # we don’t check if word exists in _dAnalyses, for it is assumed it has been done before
    aSugg = set()
    if bPlur == None:
        for sMorph in _dAnalyses.get(sFlex, []):
            if ":f" in sMorph:
                if ":s" in sMorph:
                    aSugg.add(suggMasSing(sFlex))
                elif ":p" in sMorph:
                    aSugg.add(suggMasPlur(sFlex))
            elif ":m" in sMorph:
                if ":s" in sMorph:
                    aSugg.add(suggFemSing(sFlex))
                elif ":p" in sMorph:
                    aSugg.add(suggFemPlur(sFlex))
                else:
                    aSugg.add(suggFemSing(sFlex))
                    aSugg.add(suggFemPlur(sFlex))
    elif bPlur:
        for sMorph in _dAnalyses.get(sFlex, []):
            if ":f" in sMorph:
                aSugg.add(suggMasPlur(sFlex))
            elif ":m" in sMorph:
                aSugg.add(suggFemPlur(sFlex))
    else:
        for sMorph in _dAnalyses.get(sFlex, []):
            if ":f" in sMorph:
                aSugg.add(suggMasSing(sFlex))
            elif ":m" in sMorph:
                aSugg.add(suggFemSing(sFlex))
    if aSugg:
        return u"|".join(aSugg)
    return ""


def switchPlural (sFlex):
    # we don’t check if word exists in _dAnalyses, for it is assumed it has been done before
    aSugg = set()
    for sMorph in _dAnalyses.get(sFlex, []):
        if ":s" in sMorph:
            aSugg.add(suggPlur(sFlex))
        elif ":p" in sMorph:
            aSugg.add(suggSing(sFlex))
    if aSugg:
        return u"|".join(aSugg)
    return ""


def hasSimil (sWord):
    return phonet.hasSimil(sWord)


def suggSimil (sWord, sPattern):
    "return list of words phonetically similar to sWord and whom POS is matching sPattern"
    # we don’t check if word exists in _dAnalyses, for it is assumed it has been done before
    lSet = phonet.getSimil(sWord)
    if not lSet:
        return ""
    aSugg = set()
    for sSimil in lSet:
        if sSimil not in _dAnalyses:
            _storeMorphFromFSA(sSimil)
        for sMorph in _dAnalyses.get(sSimil, []):
            if re.search(sPattern, sMorph):
                aSugg.add(sSimil)
    if aSugg:
        return u"|".join(aSugg)
    return ""


def suggCeOrCet (s):
    if re.match("(?i)[aeéèêiouyâîï]", s):
        return "cet"
    if s[0:1] == "h" or s[0:1] == "H":
        return "ce|cet"
    return "ce"


def formatNumber (s):
    nLen = len(s)
    if nLen == 10:
        sRes = s[0] + u" " + s[1:4] + u" " + s[4:7] + u" " + s[7:]                                  # nombre ordinaire
        if s.startswith("0"):
            sRes += u"|" + s[0:2] + u" " + s[2:4] + u" " + s[4:6] + u" " + s[6:8] + u" " + s[8:]    # téléphone français
            if s[1] == "4" and (s[2]=="7" or s[2]=="8" or s[2]=="9"):
                sRes += u"|" + s[0:4] + u" " + s[4:6] + u" " + s[6:8] + u" " + s[8:]                # mobile belge
            sRes += u"|" + s[0:3] + u" " + s[3:6] + u" " + s[6:8] + u" " + s[8:]                    # téléphone suisse
        sRes += u"|" + s[0:4] + u" " + s[4:7] + "-" + s[7:]                                         # téléphone canadien ou américain
        return sRes
    elif nLen == 9:
        sRes = s[0:3] + u" " + s[3:6] + u" " + s[6:]                                                # nombre ordinaire
        if s.startswith("0"):
            sRes += "|" + s[0:3] + u" " + s[3:5] + u" " + s[5:7] + u" " + s[7:9]                    # fixe belge 1
            sRes += "|" + s[0:2] + u" " + s[2:5] + u" " + s[5:7] + u" " + s[7:9]                    # fixe belge 2
        return sRes
    elif nLen < 4:
        return ""
    sRes = ""
    nEnd = nLen
    while nEnd > 0:
        nStart = max(nEnd-3, 0)
        sRes = s[nStart:nEnd] + u" " + sRes  if sRes  else s[nStart:nEnd]
        nEnd = nEnd - 3
    return sRes


def formatNF (s):
    try:
        m = re.match(u"NF[  -]?(C|E|P|Q|S|X|Z|EN(?:[  -]ISO|))[  -]?([0-9]+(?:[/‑-][0-9]+|))", s)
        if not m:
            return ""
        return u"NF " + m.group(1).upper().replace(" ", u" ").replace("-", u" ") + u" " + m.group(2).replace("/", u"‑").replace("-", u"‑")
    except:
        traceback.print_exc()
        return "# erreur #"


def undoLigature (c):
    if c == u"ﬁ":
        return "fi"
    elif c == u"ﬂ":
        return "fl"
    elif c == u"ﬀ":
        return "ff"
    elif c == u"ﬃ":
        return "ffi"
    elif c == u"ﬄ":
        return "ffl"
    elif c == u"ﬅ":
        return "ft"
    elif c == u"ﬆ":
        return "st"
    return "_"



# generated code, do not edit
def s64p_1 (s, m):
    return m.group(0).replace(".", u" ")
def p76p_1 (s, m):
    return m.group(1).replace(".", "")+"."
def c78p_1 (s, sx, m, dDA, sCountry):
    return m.group(0) != "i.e." and m.group(0) != "s.t.p."
def s78p_1 (s, m):
    return m.group(0).replace(".", "").upper()
def p78p_2 (s, m):
    return m.group(0).replace(".", "")
def c82p_1 (s, sx, m, dDA, sCountry):
    return not re.search("(?i)^etc", m.group(1))
def c87p_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":M[12]", False) and look(s[m.end():], "^\W+[a-zéèêîïâ]")
def c127p_1 (s, sx, m, dDA, sCountry):
    return option("typo") and not m.group(0).endswith("·e·s")
def c127p_2 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":[NAQ]", False)
def d127p_2 (s, m, dDA):
    return define(dDA, m.start(0), ":N:A:Q:e:i")
def c139p_1 (s, sx, m, dDA, sCountry):
    return not re.search("(?i)^(?:etc|[A-Z]|chap|cf|fig|hab|litt|circ|coll|r[eé]f|étym|suppl|bibl|bibliogr|cit|op|vol|déc|nov|oct|janv|juil|avr|sept)$", m.group(1)) and morph(dDA, (m.start(1), m.group(1)), ":", False) and morph(dDA, (m.start(2), m.group(2)), ":", False)
def s139p_1 (s, m):
    return m.group(2).capitalize()
def c150p_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, (m.start(1), m.group(1)), ":[DR]", False)
def c179p_1 (s, sx, m, dDA, sCountry):
    return not m.group(1).isdigit()
def c181p_1 (s, sx, m, dDA, sCountry):
    return _oDict.isValid(m.group(1))
def s202p_1 (s, m):
    return m.group(1)[0:-1]
def s203p_1 (s, m):
    return "nᵒˢ"  if m.group(1)[1:3] == "os"  else "nᵒ"
def c211p_1 (s, sx, m, dDA, sCountry):
    return not look(s[:m.start()], "(?i)etc$")
def s212p_1 (s, m):
    return m.group(0).replace("...", "…").rstrip(".")
def c228p_1 (s, sx, m, dDA, sCountry):
    return not re.search("^(?:etc|[A-Z]|fig|hab|litt|circ|coll|ref|étym|suppl|bibl|bibliogr|cit|vol|déc|nov|oct|janv|juil|avr|sept)$", m.group(1))
def s261p_1 (s, m):
    return m.group(0)[0] + "|" + m.group(0)[1]
def s262p_1 (s, m):
    return m.group(0)[0] + "|" + m.group(0)[1]
def s263p_1 (s, m):
    return m.group(0)[0] + "|" + m.group(0)[1]
def c272p_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(3), m.group(3)), ";S", ":[VCR]") or mbUnit(m.group(3))
def c275p_1 (s, sx, m, dDA, sCountry):
    return (not re.search("^[0-9][0-9]{1,3}$", m.group(2)) and not _oDict.isValid(m.group(3))) or morphex(dDA, (m.start(3), m.group(3)), ";S", ":[VCR]") or mbUnit(m.group(3))
def c297p_1 (s, sx, m, dDA, sCountry):
    return sCountry != "CA"
def s297p_1 (s, m):
    return " "+m.group(0)
def s343p_1 (s, m):
    return undoLigature(m.group(0))
def c389p_1 (s, sx, m, dDA, sCountry):
    return not option("mapos") and morph(dDA, (m.start(2), m.group(2)), ":V", False)
def s389p_1 (s, m):
    return m.group(1)[:-1]+u"’"
def c392p_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":V", False)
def s392p_1 (s, m):
    return m.group(1)[:-1]+u"’"
def c396p_1 (s, sx, m, dDA, sCountry):
    return option("mapos") and not look(s[:m.start()], "(?i)(?:lettre|caractère|glyphe|dimension|variable|fonction|point) *$")
def s396p_1 (s, m):
    return m.group(1)[:-1]+u"’"
def c410p_1 (s, sx, m, dDA, sCountry):
    return not re.search("(?i)^(?:onz[ei]|énième|iourte|ouistiti|ouate|one-?step|Ouagadougou|I(?:I|V|X|er|ᵉʳ|ʳᵉ|è?re))", m.group(2)) and not m.group(2).isupper() and not morph(dDA, (m.start(2), m.group(2)), ":G", False)
def s410p_1 (s, m):
    return m.group(1)[0]+u"’"
def c426p_1 (s, sx, m, dDA, sCountry):
    return not re.search("(?i)^(?:onz|énième)", m.group(2)) and morph(dDA, (m.start(2), m.group(2)), ":[me]")
def c434p_1 (s, sx, m, dDA, sCountry):
    return not re.search("^NF (?:C|E|P|Q|S|X|Z|EN(?: ISO|)) [0-9]+(?:‑[0-9]+|)", m.group(0))
def s434p_1 (s, m):
    return formatNF(m.group(0))
def s439p_1 (s, m):
    return m.group(0).replace("2", "₂").replace("3", "₃").replace("4", "₄")
def c447p_1 (s, sx, m, dDA, sCountry):
    return not look(s[:m.start()], "NF[  -]?(C|E|P|Q|X|Z|EN(?:[  -]ISO|)) *")
def s447p_1 (s, m):
    return formatNumber(m.group(0))
def c461p_1 (s, sx, m, dDA, sCountry):
    return not option("ocr")
def s461p_1 (s, m):
    return m.group(0).replace("O", "0")
def c462p_1 (s, sx, m, dDA, sCountry):
    return not option("ocr")
def s462p_1 (s, m):
    return m.group(0).replace("O", "0")
def c480p_1 (s, sx, m, dDA, sCountry):
    return not checkDate(m.group(1), m.group(2), m.group(3)) and not look(s[:m.start()], r"(?i)\bversions? +$")
def c483p_1 (s, sx, m, dDA, sCountry):
    return not checkDateWithString(m.group(1), m.group(2), m.group(3))
def c486p_1 (s, sx, m, dDA, sCountry):
    return not look(s[m.end():], r"^ +av(?:ant|\.) J(?:\.-C\.|ésus-Christ)") and not checkDay(m.group(1), m.group(2), m.group(3), m.group(4))
def s486p_1 (s, m):
    return getDay(m.group(2), m.group(3), m.group(4))
def c491p_1 (s, sx, m, dDA, sCountry):
    return not look(s[m.end():], r"^ +av(?:ant|\.) J(?:\.-C\.|ésus-Christ)") and not checkDayWithString(m.group(1), m.group(2), m.group(3), m.group(4))
def s491p_1 (s, m):
    return getDayWithString(m.group(2), m.group(3), m.group(4))
def c529p_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V0", False) or m.group(1) == "en"
def c536p_1 (s, sx, m, dDA, sCountry):
    return _oDict.isValid(m.group(1)+"-"+m.group(2)) and analyse(m.group(1)+"-"+m.group(2), ":", False)
def c540p_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":[NB]", False)
def c541p_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":[NB]", False) and not nextword1(s, m.end())
def c544p_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":N") and not re.search("(?i)^(?:aequo|nihilo|cathedra|absurdo|abrupto)", m.group(1))
def c546p_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":[NAQ]", False)
def c547p_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":N", ":[AGW]")
def c550p_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":[NAQ]", False)
def c552p_1 (s, sx, m, dDA, sCountry):
    return _oDict.isValid(m.group(1)+"-"+m.group(2)) and analyse(m.group(1)+"-"+m.group(2), ":", False)
def c556p_1 (s, sx, m, dDA, sCountry):
    return _oDict.isValid(m.group(1)+"-"+m.group(2)) and analyse(m.group(1)+"-"+m.group(2), ":", False) and morph(dDA, prevword1(s, m.start()), ":D", False, not bool(re.search("(?i)^s(?:ans|ous)$", m.group(1))))
def c560p_1 (s, sx, m, dDA, sCountry):
    return _oDict.isValid(m.group(1)+"-"+m.group(2)) and analyse(m.group(1)+"-"+m.group(2), ":N", False) and morph(dDA, prevword1(s, m.start()), ":(?:D|V0e)", False, True) and not (morph(dDA, (m.start(1), m.group(1)), ":G", False) and morph(dDA, (m.start(2), m.group(2)), ":[GYB]", False))
def s567p_1 (s, m):
    return m.group(0).replace(" ", "-")
def s568p_1 (s, m):
    return m.group(0).replace(" ", "-")
def c579p_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, prevword1(s, m.start()), ":Cs", False, True)
def s585p_1 (s, m):
    return m.group(0).replace(" ", "-")
def c591p_1 (s, sx, m, dDA, sCountry):
    return not nextword1(s, m.end())
def c593p_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, prevword1(s, m.start()), ":G")
def c597p_1 (s, sx, m, dDA, sCountry):
    return look(s[:m.start()], r"(?i)\b(?:les?|du|des|un|ces?|[mts]on) +")
def c604p_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":D", False)
def c606p_1 (s, sx, m, dDA, sCountry):
    return not ( morph(dDA, prevword1(s, m.start()), ":R", False) and look(s[m.end():], "^ +qu[e’]") )
def s654p_1 (s, m):
    return m.group(0).replace(" ", "-")
def c656p_1 (s, sx, m, dDA, sCountry):
    return not look(s[:m.start()], "(?i)quatre $")
def s656p_1 (s, m):
    return m.group(0).replace(" ", "-").replace("vingts", "vingt")
def s658p_1 (s, m):
    return m.group(0).replace(" ", "-")
def s660p_1 (s, m):
    return m.group(0).replace(" ", "-").replace("vingts", "vingt")
def s684p_1 (s, m):
    return m.group(0).replace("-", " ")
def c686p_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":D", False, False)
def s689p_1 (s, m):
    return m.group(0).replace("-", " ")
def s690p_1 (s, m):
    return m.group(0).replace("-", " ")
def c738p_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, (m.start(1), m.group(1)), ":(?:G|V0)|>(?:t(?:antôt|emps|rès)|loin|souvent|parfois|quelquefois|côte|petit) ", False) and not m.group(1)[0].isupper()
def p754p_1 (s, m):
    return m.group(0).replace("‑", "")
def p755p_1 (s, m):
    return m.group(0).replace("‑", "")
def c789s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, (m.start(0), m.group(0)), ":", False)
def c792s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":D", False)
def c793s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":A", False) and not morph(dDA, prevword1(s, m.start()), ":D", False)
def c830s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, (m.start(1), m.group(1)), ":(?:O[sp]|X)", False)
def d830s_1 (s, m, dDA):
    return select(dDA, m.start(1), m.group(1), ":V")
def d832s_1 (s, m, dDA):
    return select(dDA, m.start(1), m.group(1), ":V")
def c834s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, (m.start(1), m.group(1)), ":[YD]", False)
def d834s_1 (s, m, dDA):
    return exclude(dDA, m.start(1), m.group(1), ":V")
def d836s_1 (s, m, dDA):
    return exclude(dDA, m.start(1), m.group(1), ":V")
def c838s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, (m.start(1), m.group(1)), ":Y", False)
def d838s_1 (s, m, dDA):
    return exclude(dDA, m.start(1), m.group(1), ":V")
def c848s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":M", ":G") and not morph(dDA, (m.start(2), m.group(2)), ":N", False) and not prevword1(s, m.start())
def c858s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":E", False) and morph(dDA, (m.start(3), m.group(3)), ":M", False)
def c870s_1 (s, sx, m, dDA, sCountry):
    return option("mapos")
def s870s_1 (s, m):
    return m.group(1)[:-1]+"’"
def c877s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[GNAY]", ":(?:Q|3s)|>(?:priori|post[eé]riori|contrario|capella) ")
def c891s_1 (s, sx, m, dDA, sCountry):
    return not m.group(0).isdigit()
def s891s_1 (s, m):
    return m.group(0).replace("O", "0").replace("I", "1")
def c897s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":D.*:p", False, False)
def c900s_1 (s, sx, m, dDA, sCountry):
    return not look(s[:m.start()], r"(?i)\b[jn]e +$")
def c903s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":N.*:f:s", False)
def c909s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, nextword1(s, m.end()), ">(?:et|o[uù]) ")
def c915s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":D.*:f:[si]")
def c921s_1 (s, sx, m, dDA, sCountry):
    return m.group(0).endswith("o")
def c921s_2 (s, sx, m, dDA, sCountry):
    return m.group(0).endswith("s") and not morph(dDA, prevword1(s, m.start()), ":D.*:[me]", False, False)
def c926s_1 (s, sx, m, dDA, sCountry):
    return m.group(0).endswith("s") and not morph(dDA, prevword1(s, m.start()), ":D.*:m:p", False, False)
def c926s_2 (s, sx, m, dDA, sCountry):
    return m.group(0).endswith("é") and not morph(dDA, prevword1(s, m.start()), ":D.*:m:[si]", False, False)
def c931s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, prevword1(s, m.start()), ":V", False, True)
def c935s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":D.*:m:s", False, False)
def c938s_1 (s, sx, m, dDA, sCountry):
    return not prevword1(s, m.start()) and morph(dDA, (m.start(2), m.group(2)), ":(?:O[on]|3s)", False)
def c942s_1 (s, sx, m, dDA, sCountry):
    return m.group(0).endswith("U")
def c942s_2 (s, sx, m, dDA, sCountry):
    return m.group(0).endswith("s")
def s950s_1 (s, m):
    return m.group(0).replace("é", "e").replace("É", "E").replace("è", "e").replace("È", "E")
def c957s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":(?:V0|N.*:m:[si])", False, False)
def c963s_1 (s, sx, m, dDA, sCountry):
    return m.group(2).endswith("e") and ( re.search("(?i)^(?:quand|comme|que)$", m.group(1)) or morphex(dDA, (m.start(1), m.group(1)), ":[NV]", ":[GA]") )
def c963s_2 (s, sx, m, dDA, sCountry):
    return m.group(2).endswith("s") and not re.search("(?i)^(?:les|[mtscd]es|quels)$", m.group(1))
def c978s_1 (s, sx, m, dDA, sCountry):
    return m.group(0).endswith("u") and not morph(dDA, prevword1(s, m.start()), ":D.*:m:s", False, False)
def c978s_2 (s, sx, m, dDA, sCountry):
    return m.group(0).endswith("x") and not morph(dDA, prevword1(s, m.start()), ":D.*:m:p", False, False)
def c986s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":D.*:m:p", False, False)
def c992s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":D.*:f:s", False, False)
def c995s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":D.*:[me]:p", False, False)
def c1004s_1 (s, sx, m, dDA, sCountry):
    return m.group(0).endswith("n")
def c1004s_2 (s, sx, m, dDA, sCountry):
    return m.group(0).endswith("s")
def c1012s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":A.*:f", False) or morph(dDA, prevword1(s, m.start()), ":D:*:f", False, False)
def s1012s_1 (s, m):
    return m.group(1).replace("è", "ê").replace("È", "Ê")
def c1030s_1 (s, sx, m, dDA, sCountry):
    return not re.search("(?i)^([nv]ous|faire|en|la|lui|donnant|œuvre|h[éo]|olé|joli|Bora|couvent|dément|sapiens|très|vroum|[0-9]+)$", m.group(1)) and not (re.search("^(?:est|une?)$", m.group(1)) and look(s[:m.start()], "[’']$")) and not (m.group(1) == "mieux" and look(s[:m.start()], "(?i)qui +$"))
def s1044s_1 (s, m):
    return suggSimil(m.group(2), ":[NA].*:[pi]")
def s1046s_1 (s, m):
    return suggSimil(m.group(2), ":[NA].*:[si]")
def c1065s_1 (s, sx, m, dDA, sCountry):
    return not re.search("(?i)^avoir$", m.group(1)) and morph(dDA, (m.start(1), m.group(1)), ">avoir ", False)
def c1080s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">(?:être|mettre) ", False)
def c1111s_1 (s, sx, m, dDA, sCountry):
    return not look_chk1(dDA, s[m.end():], m.end(), r" \w[\w-]+ en ([aeo][a-zû]*)", ":V0a")
def c1131s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">abolir ", False)
def c1133s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">achever ", False)
def c1134s_1 (s, sx, m, dDA, sCountry):
    return not look(s[m.end():], r" +de?\b")
def c1143s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, prevword1(s, m.start()), ":A|>un", False)
def c1149s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">comparer ")
def c1150s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">contraindre ", False)
def c1161s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">joindre ")
def c1187s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">suffire ")
def c1188s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">talonner ")
def c1195s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">(?:prévenir|prévoir|prédire|présager|préparer|pressentir|pronostiquer|avertir|devancer|réserver) ", False)
def c1200s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">(?:ajourner|différer|reporter) ", False)
def c1267s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V.*:(?:Y|[123][sp])", ":[NAQ]:.:[si]") and m.group(2)[0].islower()
def s1267s_1 (s, m):
    return suggSimil(m.group(2), ":[NAQ]:[fe]:[si]")
def c1271s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V.*:(?:Y|[123][sp])", ":N.*:[fe]|:[AW]") and m.group(2)[0].islower() or m.group(2) == "va"
def c1271s_2 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V.*:(?:Y|[123][sp])", ":[NAQ]:.:[si]") and m.group(2)[0].islower() and hasSimil(m.group(2))
def s1271s_2 (s, m):
    return suggSimil(m.group(2), ":[NAQ]:[fe]:[si]")
def c1277s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V.*:(?:Y|[123][sp])", ":[NAQ]:.:[si]") and m.group(2)[0].islower()
def s1277s_1 (s, m):
    return suggSimil(m.group(2), ":[NAQ]:[me]:[si]")
def c1281s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V.*:(?:Y|[123][sp])", ":[NAQ]:.:[si]|:V0e.*:3[sp]|>devoir") and m.group(2)[0].islower() and hasSimil(m.group(2))
def s1281s_1 (s, m):
    return suggSimil(m.group(2), ":[NAQ]:[me]:[si]")
def c1285s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V.*:(?:Y|[123][sp])", ":[NAQ]:.:[si]") and m.group(2)[0].islower()
def s1285s_1 (s, m):
    return suggSimil(m.group(2), ":[NAQ]:.:[si]")
def c1289s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V.*:(?:Y|[123][sp])") and m.group(1)[0].islower() and not prevword1(s, m.start())
def s1289s_1 (s, m):
    return suggSimil(m.group(1), ":[NAQ]:[me]:[si]")
def c1293s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V.*:(?:Y|[123][sp])", ":[NAQ]:.:[pi]") and m.group(2)[0].islower() and not re.search(r"(?i)^quelques? soi(?:ent|t|s)\b", m.group(0))
def s1293s_1 (s, m):
    return suggSimil(m.group(2), ":[NAQ]:.:[pi]")
def c1297s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V.*:(?:Y|[123][sp])", ":[NAQ]:.:[pi]") and m.group(2)[0].islower()
def s1297s_1 (s, m):
    return suggSimil(m.group(2), ":[NAQ]:[me]:[pi]")
def c1301s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V.*:(?:Y|[123][sp])", ":[NAQ]:.:[pi]") and m.group(2)[0].islower()
def s1301s_1 (s, m):
    return suggSimil(m.group(2), ":[NAQ]:[fe]:[pi]")
def c1305s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":[123][sp]", ":[NAQ]")
def s1305s_1 (s, m):
    return suggSimil(m.group(1), ":(?:[NAQ]:[fe]:[si])")
def c1309s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:[me]", ":[YG]") and m.group(2)[0].islower()
def c1309s_2 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":[123][sp]", False)
def s1309s_2 (s, m):
    return suggSimil(m.group(2), ":Y")
def c1315s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":(?:Y|[123][sp])") and not look(s[:m.start()], "(?i)(?:dont|sauf|un à) +$")
def s1315s_1 (s, m):
    return suggSimil(m.group(1), ":[NAQ]:[me]:[si]")
def c1319s_1 (s, sx, m, dDA, sCountry):
    return m.group(1)[0].islower() and morph(dDA, (m.start(1), m.group(1)), ":V.*:[123][sp]")
def s1319s_1 (s, m):
    return suggSimil(m.group(1), ":[NA]")
def c1323s_1 (s, sx, m, dDA, sCountry):
    return m.group(1)[0].islower() and morphex(dDA, (m.start(1), m.group(1)), ":V.*:[123][sp]", ":[GNA]")
def s1323s_1 (s, m):
    return suggSimil(m.group(1), ":[NAQ]")
def c1327s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":", ":(?:[123][sp]|O[onw]|X)|ou ") and morphex(dDA, prevword1(s, m.start()), ":", ":3s", True)
def s1327s_1 (s, m):
    return suggSimil(m.group(1), ":(?:3s|Oo)")
def c1331s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":", ":(?:[123][sp]|O[onw]|X)|ou ") and morphex(dDA, prevword1(s, m.start()), ":", ":3p", True)
def s1331s_1 (s, m):
    return suggSimil(m.group(1), ":(?:3p|Oo)")
def c1335s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":", ":(?:[123][sp]|O[onw]|X)") and morphex(dDA, prevword1(s, m.start()), ":", ":1s", True)
def s1335s_1 (s, m):
    return suggSimil(m.group(1), ":(?:1s|Oo)")
def c1339s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":", ":(?:[123][sp]|O[onw]|X)") and morphex(dDA, prevword1(s, m.start()), ":", ":(?:2s|V0e)", True)
def s1339s_1 (s, m):
    return suggSimil(m.group(1), ":(?:2s|Oo)")
def c1352s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, (m.start(1), m.group(1)), ":P", False)
def c1353s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":[NAQ]")
def c1359s_1 (s, sx, m, dDA, sCountry):
    return _oDict.isValid(m.group(2)) and not morph(dDA, (m.start(2), m.group(2)), ":(?:[123][sp]|Y|P|O[on]|X)|>(?:[lmts]|surtout|guère) ", False) and not re.search("(?i)-(?:ils?|elles?|[nv]ous|je|tu|on|ce)$", m.group(2))
def s1359s_1 (s, m):
    return suggSimil(m.group(2), ":(?:V|Oo)")
def c1362s_1 (s, sx, m, dDA, sCountry):
    return not re.search("(?i)^se que?", m.group(0)) and _oDict.isValid(m.group(2)) and not morph(dDA, (m.start(2), m.group(2)), ":(?:[123][sp]|Y|P|Oo)|>[lmts] ", False) and not re.search("(?i)-(?:ils?|elles?|[nv]ous|je|tu|on|ce)$", m.group(2))
def s1362s_1 (s, m):
    return suggSimil(m.group(2), ":(?:V|Oo)")
def c1366s_1 (s, sx, m, dDA, sCountry):
    return _oDict.isValid(m.group(2)) and not morph(dDA, (m.start(2), m.group(2)), ":(?:[123][sp]|Y|P|Oo)", False) and not re.search("(?i)-(?:ils?|elles?|[nv]ous|je|tu|on|ce)$", m.group(2))
def s1366s_1 (s, m):
    return suggSimil(m.group(2), ":V")
def c1369s_1 (s, sx, m, dDA, sCountry):
    return _oDict.isValid(m.group(2)) and not morph(dDA, (m.start(2), m.group(2)), ":(?:[123][sp]|Y|P|O[onw]|X)", False) and not re.search("(?i)-(?:ils?|elles?|[nv]ous|je|tu|on|ce)$", m.group(2))
def s1369s_1 (s, m):
    return suggSimil(m.group(2), ":V")
def c1372s_1 (s, sx, m, dDA, sCountry):
    return _oDict.isValid(m.group(2)) and not morph(dDA, (m.start(2), m.group(2)), ":(?:[123][sp]|O[onw])", False)
def s1372s_1 (s, m):
    return suggSimil(m.group(2), ":[123][sp]")
def c1375s_1 (s, sx, m, dDA, sCountry):
    return _oDict.isValid(m.group(2)) and not morph(dDA, (m.start(2), m.group(2)), ":(?:[123][sp]|Y|P)|>(?:en|y|ils?) ", False) and not re.search("(?i)-(?:ils?|elles?|[nv]ous|je|tu|on|ce)$", m.group(2))
def s1375s_1 (s, m):
    return suggSimil(m.group(2), ":V")
def c1378s_1 (s, sx, m, dDA, sCountry):
    return _oDict.isValid(m.group(2)) and not morph(dDA, (m.start(2), m.group(2)), ":(?:[123][sp]|Y|P)|>(?:en|y|ils?|elles?) ", False) and not re.search("(?i)-(?:ils?|elles?|[nv]ous|je|tu|on|ce)$", m.group(2))
def s1378s_1 (s, m):
    return suggSimil(m.group(2), ":V")
def c1381s_1 (s, sx, m, dDA, sCountry):
    return _oDict.isValid(m.group(2)) and not morph(dDA, (m.start(2), m.group(2)), ":[123][sp]|>(?:en|y) ", False) and not re.search("(?i)-(?:ils?|elles?|[nv]ous|je|tu|on|dire)$", m.group(2))
def s1381s_1 (s, m):
    return suggSimil(m.group(2), ":V")
def c1399s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":(?:Y|[123][sp])", ":[GAQW]")
def c1403s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":[123][sp]", ":(?:G|N|A|Q|W|M[12])")
def c1410s_1 (s, sx, m, dDA, sCountry):
    return not m.group(1)[0].isupper() and morphex(dDA, (m.start(1), m.group(1)), ":[123][sp]", ":[GNAQM]")
def c1414s_1 (s, sx, m, dDA, sCountry):
    return not m.group(1)[0].isupper() and morphex(dDA, (m.start(1), m.group(1)), ":[123][sp]", ":[GNAQM]") and not morph(dDA, prevword1(s, m.start()), ":[NA]:[me]:si", False)
def c1418s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":[123][sp]", ":(?:G|N|A|Q|W|M[12]|T)")
def c1422s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":(?:[123][sp]|Y)", ":[GAQW]") and not morph(dDA, prevword1(s, m.start()), ":V[123].*:[123][sp]", False, False)
def c1429s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, prevword1(s, m.start()), ":[VN]", False, True)
def c1430s_1 (s, sx, m, dDA, sCountry):
    return not prevword1(s, m.start())
def c1433s_1 (s, sx, m, dDA, sCountry):
    return not look(s[:m.start()], r"(?i)\b(?:[lmts]a|leur|une|en) +$")
def c1435s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">être ") and not look(s[:m.start()], r"(?i)\bce que? ")
def c1454s_1 (s, sx, m, dDA, sCountry):
    return not re.search("(?i)^(?:côtés?|coups?|peu(?:-près|)|pics?|propos|valoir|plat-ventrismes?)", m.group(2))
def c1454s_2 (s, sx, m, dDA, sCountry):
    return re.search("(?i)^(?:côtés?|coups?|peu(?:-pr(?:ès|êts?|és?)|)|pics?|propos|valoir|plat-ventrismes?)", m.group(2))
def c1459s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":3s", False, False)
def c1462s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":(?:3s|R)", False, False) and not morph(dDA, nextword1(s, m.end()), ":Oo", False)
def c1467s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":Q", ":M[12P]")
def c1470s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ]", ":(?:Y|Oo)")
def c1474s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ]", ":(?:Y|Oo)")
def c1481s_1 (s, sx, m, dDA, sCountry):
    return not look(s[:m.start()], r"(?i)\bce que?\b")
def c1483s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":(?:M[12]|D|Oo)")
def c1488s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":[123][sp]") and not m.group(2)[0:1].isupper() and not m.group(2).startswith("tord")
def c1491s_1 (s, sx, m, dDA, sCountry):
    return not look(s[:m.start()], r"(?i)[ln]’$|(?<!-)\b(?:il|elle|on|y|n’en) +$")
def c1495s_1 (s, sx, m, dDA, sCountry):
    return not look(s[:m.start()], r"(?i)(\bque?\\b|[ln]’$|(?<!-)\b(?:il|elle|on|y|n’en) +$)")
def c1498s_1 (s, sx, m, dDA, sCountry):
    return not look(s[:m.start()], r"(?i)(\bque?\b|[ln]’$|(?<!-)\b(?:il|elle|on|y|n’en) +$)")
def c1502s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":Y", False) and not look(s[:m.start()], r"(?i)\bque? |(?:il|elle|on|n’(?:en|y)) +$")
def c1540s_1 (s, sx, m, dDA, sCountry):
    return not prevword1(s, m.start())
def c1547s_1 (s, sx, m, dDA, sCountry):
    return not nextword1(s, m.end()) or look(s[m.end():], "(?i)^ +que? ")
def c1549s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":G", ">(?:tr(?:ès|op)|peu|bien|plus|moins) |:[NAQ].*:f")
def c1553s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:f") and not re.search("^seule?s?", m.group(2))
def c1556s_1 (s, sx, m, dDA, sCountry):
    return not look(s[:m.start()], r"\b(?:[oO]h|[aA]h) +$")
def c1558s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":R")
def c1570s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ]", ":([123][sp]|Y|P|Q)|>l[ea]? ")
def c1573s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":Y")  and m.group(1) != "CE"
def c1575s_1 (s, sx, m, dDA, sCountry):
    return (m.group(0).find(",") >= 0 or morphex(dDA, (m.start(2), m.group(2)), ":G", ":[AYD]"))
def c1578s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":V[123].*:(?:Y|[123][sp])") and not morph(dDA, (m.start(2), m.group(2)), ">(?:devoir|pouvoir) ") and m.group(2)[0].islower() and m.group(1) != "CE"
def c1585s_1 (s, sx, m, dDA, sCountry):
    return not prevword1(s, m.start())
def c1587s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":V", ":[NAQ].*:[me]") or look(s[:m.start()], r"(?i)\b[cs]e +")
def c1590s_1 (s, sx, m, dDA, sCountry):
    return look(s[m.end():], "^ +[ldmtsc]es ") or ( morph(dDA, prevword1(s, m.start()), ":Cs", False, True) and not look(s[:m.start()], ", +$") and not look(s[m.end():], r"^ +(?:ils?|elles?)\b") and not morph(dDA, nextword1(s, m.end()), ":Q", False, False) )
def c1596s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":N.*:s", ":(?:A.*:[pi]|P)")
def c1618s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":N.*:p", ":(?:G|W|A.*:[si])")
def c1627s_1 (s, sx, m, dDA, sCountry):
    return m.group(1).endswith("en") or look(s[:m.start()], "^ *$")
def c1633s_1 (s, sx, m, dDA, sCountry):
    return not prevword1(s, m.start())
def c1636s_1 (s, sx, m, dDA, sCountry):
    return not m.group(1).startswith("B")
def c1651s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":E|>le ", False, False)
def c1661s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":(?:[123][sp]|Y)", ":(?:G|N|A|M[12P])") and not look(s[:m.start()], r"(?i)\bles *$")
def c1676s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":W", False) and not morph(dDA, prevword1(s, m.start()), ":V.*:3s", False, False)
def s1688s_1 (s, m):
    return m.group(1).replace("pal", "pâl")
def s1691s_1 (s, m):
    return m.group(1).replace("pal", "pâl")
def c1703s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":[AQ]", False)
def c1713s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ">(?:arriver|venir|à|revenir|partir|aller) ")
def c1718s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":P", False)
def c1729s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ]", ":(?:G|[123][sp]|W)")
def s1729s_1 (s, m):
    return m.group(1).replace(" ", "")
def c1734s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V0e", False)
def c1742s_1 (s, sx, m, dDA, sCountry):
    return not prevword1(s, m.start()) and morph(dDA, (m.start(2), m.group(2)), ":V", False)
def c1745s_1 (s, sx, m, dDA, sCountry):
    return not prevword1(s, m.start()) and morph(dDA, (m.start(2), m.group(2)), ":V", False) and not ( m.group(1) == "sans" and morph(dDA, (m.start(2), m.group(2)), ":[NY]", False) )
def c1766s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":[AQ].*:[pi]", False)
def c1769s_1 (s, sx, m, dDA, sCountry):
    return not prevword1(s, m.start())
def c1771s_1 (s, sx, m, dDA, sCountry):
    return not look(s[:m.start()], r"(?i)\b(?:d[eu]|avant|après|sur|malgré) +$")
def c1773s_1 (s, sx, m, dDA, sCountry):
    return not look(s[:m.start()], r"(?i)\b(?:d[eu]|avant|après|sur|malgré) +$") and not morph(dDA, (m.start(2), m.group(2)), ":(?:3s|Oo)", False)
def c1776s_1 (s, sx, m, dDA, sCountry):
    return not look(s[:m.start()], r"(?i)\b(?:d[eu]|avant|après|sur|malgré) +$")
def c1781s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":f") and not look(s[:m.start()], "(?i)(?:à|pas|de|[nv]ous|eux) +$")
def c1784s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":m") and not look(s[:m.start()], "(?i)(?:à|pas|de|[nv]ous|eux) +$")
def c1788s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":N.*:[fp]", ":(?:A|W|G|M[12P]|Y|[me]:i|3s)") and morph(dDA, prevword1(s, m.start()), ":R|>de ", False, True)
def s1788s_1 (s, m):
    return suggMasSing(m.group(1))
def c1792s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:[mp]") and morph(dDA, prevword1(s, m.start()), ":R|>de ", False, True)
def s1792s_1 (s, m):
    return suggFemSing(m.group(1))
def c1796s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:[fs]") and morph(dDA, prevword1(s, m.start()), ":R|>de ", False, True)
def s1796s_1 (s, m):
    return suggMasPlur(m.group(1))
def c1800s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:[ms]") and morph(dDA, prevword1(s, m.start()), ":R|>de ", False, True)
def s1800s_1 (s, m):
    return suggFemPlur(m.group(1))
def c1811s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":[123][sp]", False) and not (re.search("(?i)^(?:jamais|rien)$", m.group(3)) and look(s[:m.start()], r"\b(?:que?|plus|moins)\b"))
def c1815s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":[123][sp]", False) and not (re.search("(?i)^(?:jamais|rien)$", m.group(3)) and look(s[:m.start()], r"\b(?:que?|plus|moins)\b"))
def c1819s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(3), m.group(3)), ":[123][sp]", False) and not (re.search("(?i)^(?:jamais|rien)$", m.group(3)) and look(s[:m.start()], r"\b(?:que?|plus|moins)\b"))
def c1823s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(3), m.group(3)), ":[123][sp]", False) and not (re.search("(?i)^(?:jamais|rien)$", m.group(3)) and look(s[:m.start()], r"\b(?:que?|plus|moins)\b"))
def c1838s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, (m.start(1), m.group(1)), ":(?:Y|W|O[ow])", False) and _oDict.isValid(m.group(1))
def s1838s_1 (s, m):
    return suggVerbInfi(m.group(1))
def c1862s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, (m.start(2), m.group(2)), ":[NAQ]", False)
def c2096s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":[NAQ]", ":G")
def c2103s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":R", False, False)
def c2114s_1 (s, sx, m, dDA, sCountry):
    return not re.search("(?i)^(?:janvier|février|mars|avril|mai|juin|juillet|ao[ûu]t|septembre|octobre|novembre|décembre|vendémiaire|brumaire|frimaire|nivôse|pluviôse|ventôse|germinal|floréal|prairial|messidor|thermidor|fructidor)s?$", m.group(2))
def c2147s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">faire ", False)
def c2147s_2 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">faire ", False)
def c2166s_1 (s, sx, m, dDA, sCountry):
    return m.group(2).isdigit() or morph(dDA, (m.start(2), m.group(2)), ":B", False)
def c2179s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">prendre ", False)
def c2183s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">rester ", False)
def c2188s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">(?:sembler|para[îi]tre) ") and morphex(dDA, (m.start(3), m.group(3)), ":A", ":G")
def c2189s_1 (s, sx, m, dDA, sCountry):
    return not look(s[:m.start()], r"\b(?:une|la|cette|[mts]a|[nv]otre|de) +")
def c2192s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">tenir ", False)
def c2194s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">trier ", False)
def c2196s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">venir ", False)
def c2210s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:[pi]", ":(?:G|3p)")
def c2215s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:[pi]", ":(?:G|3p)")
def c2222s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":B", False)
def c2223s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, prevword1(s, m.start()), ":V0", False) or not morph(dDA, nextword1(s, m.end()), ":A", False)
def c2224s_1 (s, sx, m, dDA, sCountry):
    return isEndOfNG(dDA, s[m.end():], m.end())
def c2225s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":W", False)
def c2226s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":A .*:m:s", False)
def c2228s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, prevword1(s, m.start()), ":(?:R|C[sc])", False, True)
def c2229s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":B", False) or re.search("(?i)^(?:plusieurs|maintes)", m.group(1))
def c2230s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, nextword1(s, m.end()), ":[NAQ]", False, True)
def c2231s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":[NAQ]", ":V0")
def c2233s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, (m.start(1), m.group(1)), ":D", False)
def c2234s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, (m.start(1), m.group(1)), ":D.*:[me]:[si]", False)
def c2235s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, nextword1(s, m.end()), ":([AQ].*:[me]:[pi])", False, False)
def c2236s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, (m.start(2), m.group(2)), ":A", False)
def c2237s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">(?:croire|devoir|estimer|imaginer|penser) ")
def c2239s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":(?:R|D|[123]s|X)", False)
def c2240s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":D", False, False)
def c2241s_1 (s, sx, m, dDA, sCountry):
    return not look(s[:m.start()], r"(?i)\bt(?:u|oi qui)\b")
def c2242s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":D", False, False)
def c2243s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":A", False)
def c2244s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":D", False, False)
def c2245s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":W", False)
def c2246s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":[AW]", ":G")
def c2247s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":[AW]", False)
def c2248s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, (m.start(2), m.group(2)), ":Y", False)
def c2251s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":[NV]", ":D")
def c2252s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, (m.start(2), m.group(2)), ":(?:3s|X)", False)
def c2253s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":[me]", False)
def c2257s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":M[12]", False) and (morph(dDA, (m.start(2), m.group(2)), ":(?:M[12]|V)", False) or not _oDict.isValid(m.group(2)))
def c2258s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":M", False) and morph(dDA, (m.start(2), m.group(2)), ":M", False)
def c2259s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":M", False)
def c2260s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":(?:M[12]|N)") and morph(dDA, (m.start(2), m.group(2)), ":(?:M[12]|N)")
def c2261s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":MP")
def c2262s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":M[12]", False)
def c2263s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":M[12]", False)
def c2266s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":[MT]", False) and morph(dDA, prevword1(s, m.start()), ":Cs", False, True) and not look(s[:m.start()], r"\b(?:plus|moins|aussi) .* que +$")
def p2266s_1 (s, m):
    return rewriteSubject(m.group(1),m.group(2))
def c2271s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V0e", False)
def c2273s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V0e", False)
def c2275s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":(?:V0e|N)", False) and morph(dDA, (m.start(3), m.group(3)), ":[AQ]", False)
def c2277s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V0", False)
def c2279s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V0", False) and morph(dDA, (m.start(3), m.group(3)), ":[QY]", False)
def c2281s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V0a", False) and not (m.group(2) == "crainte" and look(s[:m.start()], r"\w"))
def c2283s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V0a", False) and morph(dDA, (m.start(3), m.group(3)), ":B", False) and morph(dDA, (m.start(4), m.group(4)), ":(?:Q|V1.*:Y)", False)
def c2287s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V", False)
def c2288s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V[123]")
def c2289s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V[123]", False)
def c2290s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V", False)
def c2293s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V", ":G")
def c2296s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, (m.start(2), m.group(2)), "[NAQ].*:[me]:[si]", False)
def c2298s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":[NAQ].*:[me]", ":G") and morph(dDA, (m.start(3), m.group(3)), ":[AQ].*:[me]", False)
def c2300s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":[NAQ].*:[fe]", ":G") and morph(dDA, (m.start(3), m.group(3)), ":[AQ].*:[fe]", False)
def c2302s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":[NAQ].*:[pi]", ":[123][sp]") and morph(dDA, (m.start(3), m.group(3)), ":[AQ].*:[pi]", False)
def c2305s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":[AW]")
def c2307s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":[AW]", False)
def c2309s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":[AQ]", False)
def c2311s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":W", ":3p")
def c2313s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[AW]", ":[123][sp]")
def c2317s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":[NAQ]", False) and morph(dDA, (m.start(3), m.group(3)), ":W", False) and morph(dDA, (m.start(4), m.group(4)), ":[AQ]", False)
def c2319s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":D", False, True)
def c2320s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":W\\b")
def c2323s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":[NAQ]", False)
def c2327s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":(?:N|A|Q|V0e)", False)
def c2390s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":1s", False, False)
def c2391s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":2s", False, False)
def c2392s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":3s", False, False)
def c2393s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":1p", False, False)
def c2394s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":2p", False, False)
def c2395s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":3p", False, False)
def c2396s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":[123][sp]")
def c2402s_1 (s, sx, m, dDA, sCountry):
    return isAmbiguousNAV(m.group(3)) and morph(dDA, (m.start(1), m.group(1)), ":[NAQ]", False)
def c2405s_1 (s, sx, m, dDA, sCountry):
    return isAmbiguousNAV(m.group(3)) and morph(dDA, (m.start(1), m.group(1)), ":[NAQ]", False) and not re.search("^[dD](?:’une?|e la) ", m.group(0))
def c2408s_1 (s, sx, m, dDA, sCountry):
    return isAmbiguousNAV(m.group(3)) and ( morph(dDA, (m.start(1), m.group(1)), ":[NAQ]", False) or (morphex(dDA, (m.start(1), m.group(1)), ":[NAQ]", ":3[sp]") and not prevword1(s, m.start())) )
def c2424s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, (m.start(1), m.group(1)), ":(?:G|V0)", False)
def c2434s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":[NAQ]", False)
def c2437s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":[NAQ]", False)
def c2440s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:f", False)
def c2455s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:f", ":(?:e|m|P|G|W|[123][sp]|Y)")
def c2458s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:f", ":(?:e|m|P|G|W|[123][sp]|Y)") or ( morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:f", ":[me]") and morphex(dDA, (m.start(1), m.group(1)), ":R", ">(?:e[tn]|ou) ") and not (morph(dDA, (m.start(1), m.group(1)), ":Rv", False) and morph(dDA, (m.start(3), m.group(3)), ":Y", False)) )
def c2462s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:f", ":(?:e|m|P|G|W|Y)")
def c2466s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:f", ":[GWme]")
def c2469s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:f", ":(?:e|m|G|W|V0|3s)")
def c2472s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:f", ":(?:e|m|G|W|P)")
def c2475s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:f", ":[GWme]")
def c2478s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:f", ":[GWme]")
def c2481s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:f:s", ":[GWme]")
def c2485s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:m", ":(?:e|f|P|G|W|[1-3][sp]|Y)")
def c2488s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:m", ":(?:e|f|P|G|W|[1-3][sp]|Y)") or ( morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:m", ":[fe]") and morphex(dDA, (m.start(1), m.group(1)), ":[RC]", ">(?:e[tn]|ou) ") and not (morph(dDA, (m.start(1), m.group(1)), ":(?:Rv|C)", False) and morph(dDA, (m.start(3), m.group(3)), ":Y", False)) )
def c2492s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:m", ":[efPGWY]")
def c2496s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:m", ":[efGW]")
def c2499s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:m", ":(?:e|f|G|W|V0|3s|P)") and not ( m.group(2) == "demi" and morph(dDA, nextword1(s, m.end()), ":N.*:f") )
def c2502s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:m", ":(?:e|f|G|W|V0|3s)")
def c2505s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:m", ":[efGWP]")
def c2508s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:m", ":[efGW]")
def c2511s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:m", ":[efGW]")
def s2511s_1 (s, m):
    return suggCeOrCet(m.group(2))
def c2515s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:f", ":[GWme]")
def s2515s_1 (s, m):
    return m.group(1).replace("on", "a")
def c2518s_1 (s, sx, m, dDA, sCountry):
    return re.search("(?i)^[aâeéèêiîoôuûyœæ]", m.group(2)) and morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:f", ":[eGW]")
def s2518s_1 (s, m):
    return m.group(1).replace("a", "on")
def c2518s_2 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:m", ":[efGW]")
def s2518s_2 (s, m):
    return m.group(1).replace("a", "on")
def c2525s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:m", ":[efGW]")
def c2531s_1 (s, sx, m, dDA, sCountry):
    return ( morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:s") and not (look(s[m.end():], "^ +(?:et|ou) ") and morph(dDA, nextword(s, m.end(), 2), ":[NAQ]", True, False)) ) or m.group(1) in aREGULARPLURAL
def s2531s_1 (s, m):
    return suggPlur(m.group(1))
def c2535s_1 (s, sx, m, dDA, sCountry):
    return ( morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:s") or (morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:s", ":[pi]|>avoir") and morphex(dDA, (m.start(1), m.group(1)), ":[RC]", ">(?:e[tn]|ou) ") and not (morph(dDA, (m.start(1), m.group(1)), ":Rv", False) and morph(dDA, (m.start(2), m.group(2)), ":Y", False))) ) and not (look(s[m.end():], "^ +(?:et|ou) ") and morph(dDA, nextword(s, m.end(), 2), ":[NAQ]", True, False))
def s2535s_1 (s, m):
    return suggPlur(m.group(2))
def c2540s_1 (s, sx, m, dDA, sCountry):
    return (morphex(dDA, (m.start(1), m.group(1)), ":[NAQ].*:s", ":[ipYPGW]") and not (look(s[m.end():], "^ +(?:et|ou) ") and morph(dDA, nextword(s, m.end(), 2), ":[NAQ]", True, False))) or m.group(1) in aREGULARPLURAL
def s2540s_1 (s, m):
    return suggPlur(m.group(1))
def c2545s_1 (s, sx, m, dDA, sCountry):
    return (morphex(dDA, (m.start(1), m.group(1)), ":[NAQ].*:s", ":[ipGW]") and not (look(s[m.end():], "^ +(?:et|ou) ") and morph(dDA, nextword(s, m.end(), 2), ":[NAQ]", True, False))) or m.group(1) in aREGULARPLURAL
def s2545s_1 (s, m):
    return suggPlur(m.group(1))
def c2550s_1 (s, sx, m, dDA, sCountry):
    return (morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:s", ":(?:[ipGW]|[123][sp])") and not (look(s[m.end():], "^ +(?:et|ou) ") and morph(dDA, nextword(s, m.end(), 2), ":[NAQ]", True, False))) or m.group(2) in aREGULARPLURAL
def s2550s_1 (s, m):
    return suggPlur(m.group(2))
def c2550s_2 (s, sx, m, dDA, sCountry):
    return (morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:s", ":(?:[ipGW]|[123][sp])") and not (look(s[m.end():], "^ +(?:et|ou) ") and morph(dDA, nextword(s, m.end(), 2), ":[NAQ]", True, False))) or m.group(2) in aREGULARPLURAL
def c2559s_1 (s, sx, m, dDA, sCountry):
    return (morphex(dDA, (m.start(1), m.group(1)), ":[NAQ].*:s", ":[ipPGW]") and not (look(s[m.end():], "^ +(?:et|ou) ") and morph(dDA, nextword(s, m.end(), 2), ":[NAQ]", True, False))) or m.group(1) in aREGULARPLURAL
def s2559s_1 (s, m):
    return suggPlur(m.group(1))
def c2569s_1 (s, sx, m, dDA, sCountry):
    return (morphex(dDA, (m.start(1), m.group(1)), ":[NAQ].*:s", ":[ip]|>o(?:nde|xydation|or)\\b") and morphex(dDA, prevword1(s, m.start()), ":(?:G|[123][sp])", ":[AD]", True)) or m.group(1) in aREGULARPLURAL
def s2569s_1 (s, m):
    return suggPlur(m.group(1))
def c2575s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":[NAQ].*:s", ":[ip]") or m.group(1) in aREGULARPLURAL
def s2575s_1 (s, m):
    return suggPlur(m.group(1))
def c2579s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":[NAQ].*:s", ":[ip]") or m.group(1) in aREGULARPLURAL
def s2579s_1 (s, m):
    return suggPlur(m.group(1))
def c2583s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":[NAQ].*:p", ":[123][sp]|:[si]")
def s2583s_1 (s, m):
    return suggSing(m.group(1))
def c2587s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:p")
def s2587s_1 (s, m):
    return suggSing(m.group(1))
def c2590s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:p") or ( morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:p", ":[si]") and morphex(dDA, (m.start(1), m.group(1)), ":[RC]", ">(?:e[tn]|ou)") and not (morph(dDA, (m.start(1), m.group(1)), ":Rv", False) and morph(dDA, (m.start(2), m.group(2)), ":Y", False)) )
def s2590s_1 (s, m):
    return suggSing(m.group(2))
def c2594s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":[NAQ].*:p", ":[siGW]")
def s2594s_1 (s, m):
    return suggSing(m.group(1))
def c2598s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:p")
def c2598s_2 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:p")
def s2598s_2 (s, m):
    return suggSing(m.group(2))
def c2601s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(3), m.group(3)), ":[NAQ].*:p") or ( morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:p", ":[si]") and morphex(dDA, (m.start(1), m.group(1)), ":[RC]", ">(?:e[tn]|ou)") and not (morph(dDA, (m.start(1), m.group(1)), ":Rv", False) and morph(dDA, (m.start(3), m.group(3)), ":Y", False)) )
def c2601s_2 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(3), m.group(3)), ":[NAQ].*:p") or ( morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:p", ":[si]") and morphex(dDA, (m.start(1), m.group(1)), ":[RC]", ">(?:e[tn]|ou)") and not (morph(dDA, (m.start(1), m.group(1)), ":Rv", False) and morph(dDA, (m.start(3), m.group(3)), ":Y", False)) )
def s2601s_2 (s, m):
    return suggSing(m.group(3))
def c2606s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:p", ":[siGW]")
def c2606s_2 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:p", ":[siGW]")
def s2606s_2 (s, m):
    return suggSing(m.group(2))
def c2610s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":[NAQ].*:p", ":[siGW]")
def s2610s_1 (s, m):
    return suggSing(m.group(1))
def c2614s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:p", ":[siGW]")
def c2618s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:p", ":[siG]")
def c2622s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":[NAQ].*:p", ":[siGW]") and not morph(dDA, prevword(s, m.start(), 2), ":B", False)
def s2622s_1 (s, m):
    return suggSing(m.group(1))
def c2665s_1 (s, sx, m, dDA, sCountry):
    return (morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:s") and not re.search("(?i)^(janvier|février|mars|avril|mai|juin|juillet|ao[ûu]t|septembre|octobre|novembre|décembre|rue|route|ruelle|place|boulevard|avenue|allée|chemin|sentier|square|impasse|cour|quai|chaussée|côte|vendémiaire|brumaire|frimaire|nivôse|pluviôse|ventôse|germinal|floréal|prairial|messidor|thermidor|fructidor)$", m.group(2))) or m.group(2) in aREGULARPLURAL
def s2665s_1 (s, m):
    return suggPlur(m.group(2))
def c2671s_1 (s, sx, m, dDA, sCountry):
    return (morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:s") and not morph(dDA, prevword1(s, m.start()), ":N", False) and not re.search("(?i)^(janvier|février|mars|avril|mai|juin|juillet|ao[ûu]t|septembre|octobre|novembre|décembre|rue|route|ruelle|place|boulevard|avenue|allée|chemin|sentier|square|impasse|cour|quai|chaussée|côte|vendémiaire|brumaire|frimaire|nivôse|pluviôse|ventôse|germinal|floréal|prairial|messidor|thermidor|fructidor)$", m.group(2))) or m.group(2) in aREGULARPLURAL
def s2671s_1 (s, m):
    return suggPlur(m.group(2))
def c2677s_1 (s, sx, m, dDA, sCountry):
    return (morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:s") or m.group(1) in aREGULARPLURAL) and not look(s[:m.start()], r"(?i)\b(?:le|un|ce|du) +$")
def s2677s_1 (s, m):
    return suggPlur(m.group(1))
def c2681s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:p") and not re.search("(?i)^(janvier|février|mars|avril|mai|juin|juillet|ao[ûu]t|septembre|octobre|novembre|décembre|rue|route|ruelle|place|boulevard|avenue|allée|chemin|sentier|square|impasse|cour|quai|chaussée|côte|vendémiaire|brumaire|frimaire|nivôse|pluviôse|ventôse|germinal|floréal|prairial|messidor|thermidor|fructidor|Rois|Corinthiens|Thessaloniciens)$", m.group(1))
def s2681s_1 (s, m):
    return suggSing(m.group(1))
def c2685s_1 (s, sx, m, dDA, sCountry):
    return (m.group(1) != "1" and m.group(1) != "0" and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:s") and not re.search("(?i)^(janvier|février|mars|avril|mai|juin|juillet|ao[ûu]t|septembre|octobre|novembre|décembre|rue|route|ruelle|place|boulevard|avenue|allée|chemin|sentier|square|impasse|cour|quai|chaussée|côte|vendémiaire|brumaire|frimaire|nivôse|pluviôse|ventôse|germinal|floréal|prairial|messidor|thermidor|fructidor)$", m.group(2))) or m.group(1) in aREGULARPLURAL
def s2685s_1 (s, m):
    return suggPlur(m.group(2))
def c2693s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:f:p", ":(?:V0e|[NAQ].*:[me]:[si])")
def c2693s_2 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:m:p", ":(?:V0e|[NAQ].*:[me]:[si])")
def c2693s_3 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:f:[si]", ":(?:V0e|[NAQ].*:[me]:[si])")
def c2697s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:f:s", ":(?:V0e|[NAQ].*:[me]:[pi])")
def c2697s_2 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:m:s", ":(?:V0e|[NAQ].*:[me]:[pi])")
def c2697s_3 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:f:[pi]", ":(?:V0e|[NAQ].*:[me]:[pi])")
def c2701s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:m:p", ":(?:V0e|[NAQ].*:[fe]:[si])")
def c2701s_2 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:f:p", ":(?:V0e|[NAQ].*:[fe]:[si])")
def c2701s_3 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:m:[si]", ":(?:V0e|[NAQ].*:[fe]:[si])")
def c2705s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:m:s", ":(?:V0e|[NAQ].*:[fe]:[pi])")
def c2705s_2 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:f:s", ":(?:V0e|[NAQ].*:[fe]:[pi])")
def c2705s_3 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:m:[pi]", ":(?:V0e|[NAQ].*:[fe]:[pi])")
def c2717s_1 (s, sx, m, dDA, sCountry):
    return not look(s[:m.start()], r"\btel(?:le|)s? +$")
def c2720s_1 (s, sx, m, dDA, sCountry):
    return not look(s[:m.start()], r"\btel(?:le|)s? +$")
def s2720s_1 (s, m):
    return m.group(1)[:-1]
def c2724s_1 (s, sx, m, dDA, sCountry):
    return not look(s[:m.start()], r"\btel(?:le|)s? +$") and morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:f", ":[me]")
def c2728s_1 (s, sx, m, dDA, sCountry):
    return not look(s[:m.start()], r"\btel(?:le|)s? +$") and morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:m", ":[fe]")
def c2732s_1 (s, sx, m, dDA, sCountry):
    return not look(s[:m.start()], r"\btel(?:le|)s? +$") and morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:f", ":[me]")
def c2736s_1 (s, sx, m, dDA, sCountry):
    return not look(s[:m.start()], r"\btel(?:le|)s? +$") and morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:m", ":[fe]")
def c2752s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":V0e", False)
def c2755s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":V0e", False) and morphex(dDA, (m.start(4), m.group(4)), ":[NAQ].*:m", ":[fe]")
def s2755s_1 (s, m):
    return m.group(1).replace("lle", "l")
def c2760s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":V0e", False)
def c2763s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":V0e", False) and morphex(dDA, (m.start(4), m.group(4)), ":[NAQ].*:f", ":[me]")
def s2763s_1 (s, m):
    return m.group(1).replace("l", "lle")
def c2782s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">trouver ", False) and morphex(dDA, (m.start(3), m.group(3)), ":A.*:(?:f|m:p)", ":(?:G|3[sp]|M[12P])")
def s2782s_1 (s, m):
    return suggMasSing(m.group(3))
def c2793s_1 (s, sx, m, dDA, sCountry):
    return ((morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:m") and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:f")) or (morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:f") and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:m"))) and not apposition(m.group(1), m.group(2))
def s2793s_1 (s, m):
    return switchGender(m.group(2))
def c2793s_2 (s, sx, m, dDA, sCountry):
    return ((morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:s") and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:p")) or (morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:p") and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:s"))) and not apposition(m.group(1), m.group(2))
def s2793s_2 (s, m):
    return switchPlural(m.group(2))
def c2801s_1 (s, sx, m, dDA, sCountry):
    return ((morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:m") and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:f")) or (morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:f") and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:m"))) and not apposition(m.group(1), m.group(2)) and morph(dDA, prevword1(s, m.start()), ":[VRX]", True, True)
def s2801s_1 (s, m):
    return switchGender(m.group(2))
def c2801s_2 (s, sx, m, dDA, sCountry):
    return ((morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:p") and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:s")) or (morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:s") and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:p"))) and not apposition(m.group(1), m.group(2)) and morph(dDA, prevword1(s, m.start()), ":[VRX]", True, True)
def s2801s_2 (s, m):
    return switchPlural(m.group(2))
def c2813s_1 (s, sx, m, dDA, sCountry):
    return ((morphex(dDA, (m.start(1), m.group(1)), ":[NAQ].*:m", ":[GYfe]") and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:f")) or (morphex(dDA, (m.start(1), m.group(1)), ":[NAQ].*:f", ":[GYme]") and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:m"))) and not apposition(m.group(1), m.group(2)) and morph(dDA, prevword1(s, m.start()), ":[VRX]", True, True)
def s2813s_1 (s, m):
    return switchGender(m.group(2))
def c2813s_2 (s, sx, m, dDA, sCountry):
    return ((morphex(dDA, (m.start(1), m.group(1)), ":[NAQ].*:p", ":[GYsi]") and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:s")) or (morphex(dDA, (m.start(1), m.group(1)), ":[NAQ].*:s", ":[GYpi]") and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:p"))) and not apposition(m.group(1), m.group(2)) and morph(dDA, prevword1(s, m.start()), ":[VRX]", True, True)
def s2813s_2 (s, m):
    return switchPlural(m.group(2))
def c2825s_1 (s, sx, m, dDA, sCountry):
    return ((morphex(dDA, (m.start(1), m.group(1)), ":[NAQ].*:m", ":(?:[Gfe]|V0e|Y)") and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:f")) or (morphex(dDA, (m.start(1), m.group(1)), ":[NAQ].*:f", ":(?:[Gme]|V0e|Y)") and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:m"))) and not apposition(m.group(1), m.group(2)) and morph(dDA, prevword1(s, m.start()), ":[VRX]", True, True)
def s2825s_1 (s, m):
    return switchGender(m.group(2))
def c2825s_2 (s, sx, m, dDA, sCountry):
    return ((morphex(dDA, (m.start(1), m.group(1)), ":[NAQ].*:p", ":(?:[Gsi]|V0e|Y)") and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:s")) or (morphex(dDA, (m.start(1), m.group(1)), ":[NAQ].*:s", ":(?:[Gpi]|V0e|Y)") and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:p"))) and not apposition(m.group(1), m.group(2)) and morph(dDA, prevword1(s, m.start()), ":[VRX]", True, True)
def s2825s_2 (s, m):
    return switchPlural(m.group(2))
def c2843s_1 (s, sx, m, dDA, sCountry):
    return not re.search("(?i)^air$", m.group(1)) and not m.group(2).startswith("seul") and ((morph(dDA, (m.start(1), m.group(1)), ":m") and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:f")) or (morph(dDA, (m.start(1), m.group(1)), ":f") and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:m"))) and not apposition(m.group(1), m.group(2)) and not look(s[:m.start()], r"\b(?:et|ou|de) +$")
def s2843s_1 (s, m):
    return switchGender(m.group(2), False)
def c2843s_2 (s, sx, m, dDA, sCountry):
    return not re.search("(?i)^air$", m.group(1)) and not m.group(2).startswith("seul") and morph(dDA, (m.start(1), m.group(1)), ":[si]") and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:p") and not apposition(m.group(1), m.group(2)) and not look(s[:m.start()], r"\b(?:et|ou|de) +$")
def s2843s_2 (s, m):
    return suggSing(m.group(2))
def c2852s_1 (s, sx, m, dDA, sCountry):
    return not m.group(2).startswith("seul") and ((morph(dDA, (m.start(1), m.group(1)), ":m") and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:f")) or (morph(dDA, (m.start(1), m.group(1)), ":f") and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:m"))) and not morph(dDA, prevword1(s, m.start()), ":[NAQ]", False, False) and not apposition(m.group(1), m.group(2))
def s2852s_1 (s, m):
    return switchGender(m.group(2), False)
def c2852s_2 (s, sx, m, dDA, sCountry):
    return not re.search("(?i)^air$", m.group(1)) and not m.group(2).startswith("seul") and morph(dDA, (m.start(1), m.group(1)), ":[si]") and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:p") and not morph(dDA, prevword1(s, m.start()), ":[NAQ]", False, False) and not apposition(m.group(1), m.group(2))
def s2852s_2 (s, m):
    return suggSing(m.group(2))
def c2867s_1 (s, sx, m, dDA, sCountry):
    return m.group(1) != "fois" and not m.group(2).startswith("seul") and ((morphex(dDA, (m.start(1), m.group(1)), ":[NAQ].*:m", ":[fe]") and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:f")) or (morphex(dDA, (m.start(1), m.group(1)), ":[NAQ].*:f", ":[me]") and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:m"))) and morph(dDA, prevword1(s, m.start()), ":[VRBX]", True, True) and not apposition(m.group(1), m.group(2))
def s2867s_1 (s, m):
    return switchGender(m.group(2), True)
def c2867s_2 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:[pi]", False) and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:s") and morph(dDA, prevword1(s, m.start()), ":[VRBX]", True, True) and not apposition(m.group(1), m.group(2))
def s2867s_2 (s, m):
    return suggPlur(m.group(2))
def c2888s_1 (s, sx, m, dDA, sCountry):
    return m.group(1) != "fois" and morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:[si]", False) and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:p") and not m.group(2).startswith("seul") and not apposition(m.group(1), m.group(2)) and not look(s[:m.start()], r"\b(?:et|ou|d’) *$")
def s2888s_1 (s, m):
    return suggSing(m.group(2))
def c2892s_1 (s, sx, m, dDA, sCountry):
    return m.group(1) != "fois" and morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:[si]", False) and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:p") and not m.group(2).startswith("seul") and not apposition(m.group(1), m.group(2)) and not morph(dDA, prevword1(s, m.start()), ":[NAQB]", False, False)
def s2892s_1 (s, m):
    return suggSing(m.group(2))
def c2902s_1 (s, sx, m, dDA, sCountry):
    return not m.group(3).startswith("seul") and morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:[me]", ":(?:B|G|V0|f)") and morph(dDA, (m.start(3), m.group(3)), ":[NAQ].*:f") and not apposition(m.group(2), m.group(3)) and not look(s[:m.start()], r"\b(?:et|ou|de) +$")
def s2902s_1 (s, m):
    return suggMasPlur(m.group(3))  if re.search("(?i)^(?:certains|quels)", m.group(1)) else suggMasSing(m.group(3))
def c2908s_1 (s, sx, m, dDA, sCountry):
    return not m.group(3).startswith("seul") and morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:[me]", ":(?:B|G|V0|f)") and morph(dDA, (m.start(3), m.group(3)), ":[NAQ].*:f") and not apposition(m.group(2), m.group(3)) and not morph(dDA, prevword1(s, m.start()), ":[NAQ]|>(?:et|ou) ", False, False)
def s2908s_1 (s, m):
    return suggMasPlur(m.group(3))  if re.search("(?i)^(?:certains|quels)", m.group(1)) else suggMasSing(m.group(3))
def c2916s_1 (s, sx, m, dDA, sCountry):
    return not m.group(3).startswith("seul") and morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:m", ":(?:B|G|e|V0|f)") and morph(dDA, (m.start(3), m.group(3)), ":[NAQ].*:f") and not apposition(m.group(2), m.group(3)) and not look(s[:m.start()], r"\b(?:et|ou|de) +$")
def s2916s_1 (s, m):
    return suggMasSing(m.group(3))
def c2921s_1 (s, sx, m, dDA, sCountry):
    return not m.group(3).startswith("seul") and morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:m", ":(?:B|G|e|V0|f)") and morph(dDA, (m.start(3), m.group(3)), ":[NAQ].*:f") and not apposition(m.group(2), m.group(3)) and not morph(dDA, prevword1(s, m.start()), ":[NAQ]|>(?:et|ou) ", False, False)
def s2921s_1 (s, m):
    return suggMasSing(m.group(3))
def c2928s_1 (s, sx, m, dDA, sCountry):
    return m.group(2) != "fois" and not m.group(3).startswith("seul") and morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:[fe]", ":(?:B|G|V0|m)") and morph(dDA, (m.start(3), m.group(3)), ":[NAQ].*:m") and not apposition(m.group(2), m.group(3)) and not look(s[:m.start()], r"\b(?:et|ou|de) +$")
def s2928s_1 (s, m):
    return suggFemPlur(m.group(3))  if re.search("(?i)^(?:certaines|quelles)", m.group(1))  else suggFemSing(m.group(3))
def c2934s_1 (s, sx, m, dDA, sCountry):
    return m.group(2) != "fois" and not m.group(3).startswith("seul") and morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:[fe]", ":(?:B|G|V0|m)") and morph(dDA, (m.start(3), m.group(3)), ":[NAQ].*:m") and not apposition(m.group(2), m.group(3)) and not morph(dDA, prevword1(s, m.start()), ":[NAQ]|>(?:et|ou) ", False, False)
def s2934s_1 (s, m):
    return suggFemPlur(m.group(3))  if re.search("(?i)^(?:certaines|quelles)", m.group(1))  else suggFemSing(m.group(3))
def c2942s_1 (s, sx, m, dDA, sCountry):
    return m.group(2) != "fois" and not m.group(3).startswith("seul") and not re.search("(?i)^quelque chose", m.group(0)) and ((morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:m", ":(?:B|e|G|V0|f)") and morph(dDA, (m.start(3), m.group(3)), ":[NAQ].*:f")) or (morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:f", ":(?:B|e|G|V0|m)") and morph(dDA, (m.start(3), m.group(3)), ":[NAQ].*:m"))) and not apposition(m.group(2), m.group(3)) and not look(s[:m.start()], r"\b(?:et|ou|de) +$")
def s2942s_1 (s, m):
    return switchGender(m.group(3), m.group(1).endswith("s"))
def c2947s_1 (s, sx, m, dDA, sCountry):
    return m.group(2) != "fois" and not m.group(3).startswith("seul") and not re.search("(?i)^quelque chose", m.group(0)) and ((morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:m", ":(?:B|e|G|V0|f)") and morph(dDA, (m.start(3), m.group(3)), ":[NAQ].*:f")) or (morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:f", ":(?:B|e|G|V0|m)") and morph(dDA, (m.start(3), m.group(3)), ":[NAQ].*:m"))) and not apposition(m.group(2), m.group(3)) and not morph(dDA, prevword1(s, m.start()), ":[NAQ]|>(?:et|ou) ", False, False)
def s2947s_1 (s, m):
    return switchGender(m.group(3), m.group(1).endswith("s"))
def c2956s_1 (s, sx, m, dDA, sCountry):
    return not m.group(2).startswith("seul") and morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:[si]", False) and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:p") and not apposition(m.group(1), m.group(2)) and not look(s[:m.start()], r"\b(?:et|ou|de) +$")
def s2956s_1 (s, m):
    return suggSing(m.group(2))
def c2961s_1 (s, sx, m, dDA, sCountry):
    return not m.group(2).startswith("seul") and morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:[si]", False) and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:p") and not apposition(m.group(1), m.group(2)) and not morph(dDA, prevword1(s, m.start()), ":[NAQ]|>(?:et|ou) ", False, False)
def s2961s_1 (s, m):
    return suggSing(m.group(2))
def c2968s_1 (s, sx, m, dDA, sCountry):
    return not m.group(2).startswith("seul") and morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:[si]", False) and morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:p", ":[GWi]") and not apposition(m.group(1), m.group(2)) and not look(s[:m.start()], r"\b(?:et|ou|de) +$")
def s2968s_1 (s, m):
    return suggSing(m.group(2))
def c2973s_1 (s, sx, m, dDA, sCountry):
    return not m.group(2).startswith("seul") and morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:[si]", False) and morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:p", ":[GWi]") and not apposition(m.group(1), m.group(2)) and not morph(dDA, prevword1(s, m.start()), ":[NAQ]|>(?:et|ou) ", False, False)
def s2973s_1 (s, m):
    return suggSing(m.group(2))
def c2980s_1 (s, sx, m, dDA, sCountry):
    return not m.group(2).startswith("seul") and morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:[pi]") and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:s") and not apposition(m.group(1), m.group(2))
def s2980s_1 (s, m):
    return suggPlur(m.group(2))
def c2985s_1 (s, sx, m, dDA, sCountry):
    return not m.group(2).startswith("seul") and morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:[pi]") and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:s") and not morph(dDA, (m.start(3), m.group(3)), ":A", False) and not apposition(m.group(1), m.group(2))
def s2985s_1 (s, m):
    return suggPlur(m.group(2))
def c2991s_1 (s, sx, m, dDA, sCountry):
    return not m.group(2).startswith("seul") and morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:[pi]", False) and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:s") and not apposition(m.group(1), m.group(2)) and not look(s[:m.start()], r"(?i)\bune? de ")
def s2991s_1 (s, m):
    return suggPlur(m.group(2))
def c3024s_1 (s, sx, m, dDA, sCountry):
    return (morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:p") and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:[pi]") and morph(dDA, (m.start(3), m.group(3)), ":[NAQ].*:s")) or (morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:s") and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:[si]") and morph(dDA, (m.start(3), m.group(3)), ":[NAQ].*:p"))
def s3024s_1 (s, m):
    return switchPlural(m.group(3))
def c3029s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:[pi]") and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:[pi]") and morph(dDA, (m.start(3), m.group(3)), ":[NAQ].*:s")
def s3029s_1 (s, m):
    return suggPlur(m.group(3))
def c3033s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:[pi]", False) and morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:[pi]", ":G") and morph(dDA, (m.start(4), m.group(4)), ":[NAQ].*:s") and not look(s[:m.start()], r"(?i)\bune? de ")
def s3033s_1 (s, m):
    return suggPlur(m.group(4))
def c3038s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:[si]", False) and morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:[si]", ":G") and morph(dDA, (m.start(4), m.group(4)), ":[NAQ].*:p")
def s3038s_1 (s, m):
    return suggSing(m.group(4))
def c3048s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:(?:m|f:p)", ":(?:G|P|[fe]:[is]|V0|3[sp])") and not apposition(m.group(1), m.group(2))
def s3048s_1 (s, m):
    return suggFemSing(m.group(2))
def c3052s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:(?:f|m:p)", ":(?:G|P|[me]:[is]|V0|3[sp])") and not apposition(m.group(1), m.group(2))
def s3052s_1 (s, m):
    return suggMasSing(m.group(2))
def c3056s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:f|>[aéeiou].*:e", False) and morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:(?:f|m:p)", ":(?:G|P|m:[is]|V0|3[sp])") and not apposition(m.group(1), m.group(2))
def s3056s_1 (s, m):
    return suggMasSing(m.group(2))
def c3060s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":[NAQ].*:m", ":G|>[aéeiou].*:[ef]") and morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:(?:f|m:p)", ":(?:G|P|[me]:[is]|V0|3[sp])") and not apposition(m.group(2), m.group(3))
def s3060s_1 (s, m):
    return suggMasSing(m.group(3))
def c3065s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":[NAQ].*:m", ":G|>[aéeiou].*:[ef]") and not morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:f|>[aéeiou].*:e", False) and morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:(?:f|m:p)", ":(?:G|P|[me]:[is]|V0|3[sp])") and not apposition(m.group(2), m.group(3))
def s3065s_1 (s, m):
    return suggMasSing(m.group(3))
def c3070s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:s", ":(?:G|P|[me]:[ip]|V0|3[sp])") and not apposition(m.group(1), m.group(2))
def s3070s_1 (s, m):
    return suggPlur(m.group(2))
def c3088s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":B.*:p", False) and m.group(2) != "cents"
def c3123s_1 (s, sx, m, dDA, sCountry):
    return not prevword1(s, m.start())
def c3124s_1 (s, sx, m, dDA, sCountry):
    return not prevword1(s, m.start())
def c3125s_1 (s, sx, m, dDA, sCountry):
    return not prevword1(s, m.start())
def c3131s_1 (s, sx, m, dDA, sCountry):
    return not look(s[:m.start()], r"(?i)\bquatre $")
def c3134s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, nextword1(s, m.end()), ":B", False) and not look(s[:m.start()], r"(?i)\b(?:numéro|page|chapitre|référence|année|test|série)s? +$")
def c3145s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, nextword1(s, m.end()), ":B|>une?", False, True) and not look(s[:m.start()], r"(?i)\b(?:numéro|page|chapitre|référence|année|test|série)s? +$")
def c3149s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, nextword1(s, m.end()), ":B|>une?", False, False)
def c3152s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:[pi]", ":G") and morphex(dDA, prevword1(s, m.start()), ":[VR]", ":B", True)
def c3157s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, nextword1(s, m.end()), ":B") or (morph(dDA, prevword1(s, m.start()), ":B") and morph(dDA, nextword1(s, m.end()), ":[NAQ]", False))
def c3168s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">faire ", False)
def c3171s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">faire ", False) and morph(dDA, (m.start(3), m.group(3)), ":(?:N|MP)")
def s3217s_1 (s, m):
    return m.group(1).rstrip("e")
def c3222s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":(?:V0e|W)|>très", False)
def c3230s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">(?:co[ûu]ter|payer) ", False)
def c3247s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">donner ", False)
def c3262s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">(?:mettre|mise) ", False)
def c3274s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">(?:avoir|perdre) ", False)
def c3277s_1 (s, sx, m, dDA, sCountry):
    return not look(s[:m.start()], r"(?i)\b(?:lit|fauteuil|armoire|commode|guéridon|tabouret|chaise)s?\b")
def c3284s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, prevword1(s, m.start()), ":(?:V|[NAQ].*:s)", ":(?:[NA]:.:[pi]|V0e.*:[123]p)", True)
def c3333s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">(?:aller|partir) ", False)
def c3341s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":V0e.*:3p", False, False) or morph(dDA, nextword1(s, m.end()), ":Q", False, False)
def c3359s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">(?:être|devenir|para[îi]tre|rendre|sembler) ", False)
def s3359s_1 (s, m):
    return m.group(2).replace("oc", "o")
def c3381s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">tenir ")
def c3395s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">mettre ", False)
def c3396s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">faire ", False)
def c3416s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">(?:être|aller) ", False)
def s3418s_1 (s, m):
    return m.group(1).replace("auspice", "hospice")
def s3420s_1 (s, m):
    return m.group(1).replace("auspice", "hospice")
def c3441s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, nextword1(s, m.end()), ":[AQ]")
def s3455s_1 (s, m):
    return m.group(1).replace("cane", "canne")
def c3462s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">(?:appuyer|battre|frapper|lever|marcher) ", False)
def s3462s_1 (s, m):
    return m.group(2).replace("cane", "canne")
def c3468s_1 (s, sx, m, dDA, sCountry):
    return not re.search("^C(?:annes|ANNES)", m.group(1))
def c3471s_1 (s, sx, m, dDA, sCountry):
    return not re.search("^C(?:annes|ANNES)", m.group(1))
def c3486s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">faire ", False)
def c3494s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V0a", False)
def c3496s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, prevword1(s, m.start()), ":[VR]", False)
def c3500s_1 (s, sx, m, dDA, sCountry):
    return not re.search("(?i)^à cor et à cri$", m.group(0))
def c3507s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">tordre ", False)
def c3509s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">rendre ", False)
def c3520s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">couper ")
def c3521s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">(?:avoir|donner) ", False)
def c3533s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V.[^:]:(?!Q)")
def c3539s_1 (s, sx, m, dDA, sCountry):
    return not look(s[:m.start()], r"(?i)\b(?:[lmtsc]es|des?|[nv]os|leurs|quels) +$")
def c3550s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, nextword1(s, m.end()), ":[GV]", ":[NAQ]", True)
def c3553s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, nextword1(s, m.end()), ":[GV]", ":[NAQ]")
def c3556s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, nextword1(s, m.end()), ":[GV]", ":[NAQ]", True)
def c3559s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, nextword1(s, m.end()), ":G", ":[NAQ]")
def c3562s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V0e", False)
def s3562s_1 (s, m):
    return m.group(2).replace("nd", "nt")
def c3572s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, prevword1(s, m.start()), ":V0e", False, False)
def c3578s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ">(?:abandonner|céder|résister) ", False) and not look(s[m.end():], "^ d(?:e |’)")
def s3591s_1 (s, m):
    return m.group(1).replace("nt", "mp")
def c3606s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V0e", False) and morph(dDA, (m.start(3), m.group(3)), ":(?:Y|Oo)", False)
def s3606s_1 (s, m):
    return m.group(2).replace("sens", "cens")
def s3615s_1 (s, m):
    return m.group(1).replace("o", "ô")
def c3630s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V0a", False)
def c3647s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ">(?:desceller|desseller) ", False)
def s3647s_1 (s, m):
    return m.group(2).replace("descell", "décel").replace("dessell", "décel")
def c3651s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">(?:desceller|desseller) ", False)
def s3651s_1 (s, m):
    return m.group(1).replace("descell", "décel").replace("dessell", "décel")
def c3665s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V0", False)
def s3665s_1 (s, m):
    return m.group(2).replace("î", "i")
def c3668s_1 (s, sx, m, dDA, sCountry):
    return not look(s[:m.start()], r"(?i)\b(?:[vn]ous|lui|leur|et toi) +$|[nm]’$")
def s3676s_1 (s, m):
    return m.group(1).replace("and", "ant")
def c3682s_1 (s, sx, m, dDA, sCountry):
    return not ( m.group(1) == "bonne" and look(s[:m.start()], r"(?i)\bune +$") and look(s[m.end():], "(?i)^ +pour toute") )
def c3685s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">(?:faire|perdre|donner) ", False)
def c3710s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":D")
def s3780s_1 (s, m):
    return m.group(0)[:-1].replace(" ", "-")+u"à"
def c3781s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V", ":[NAQ]")
def c3782s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":[NAQ]", ":[123][sp]")
def c3786s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[123][sp]", ":[GQ]")
def c3788s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[123][sp]", ":[GQ]")
def c3792s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[123][sp]", ":[GQ]")
def c3800s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":Y", ":[NA].*:[pe]") and not look(s[:m.start()], r"(?i)\b[ld]es +$")
def c3808s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">soulever ", False)
def s3808s_1 (s, m):
    return m.group(1)[3:]
def c3820s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">(?:être|habiter|trouver|situer|rester|demeurer?) ", False)
def c3831s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V0a", False)
def c3835s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V0a", False)
def c3849s_1 (s, sx, m, dDA, sCountry):
    return not (m.group(1) == "Notre" and look(s[m.end():], "Père"))
def s3849s_1 (s, m):
    return m.group(1).replace("otre", "ôtre")
def c3851s_1 (s, sx, m, dDA, sCountry):
    return not look(s[:m.start()], r"(?i)\b(les?|la|du|des|aux?) +") and morph(dDA, (m.start(2), m.group(2)), ":[NAQ]", False)
def s3851s_1 (s, m):
    return m.group(1).replace("ôtre", "otre").rstrip("s")
def c3859s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":D", False, False)
def c3870s_1 (s, sx, m, dDA, sCountry):
    return not prevword1(s, m.start())
def c3873s_1 (s, sx, m, dDA, sCountry):
    return ( re.search("^[nmts]e$", m.group(2)) or (not re.search("(?i)^(?:confiance|envie|peine|prise|crainte|affaire|hâte|force|recours|somme)$", m.group(2)) and morphex(dDA, (m.start(2), m.group(2)), ":[123][sp]", ":[AG]")) ) and not prevword1(s, m.start())
def c3878s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V.*:(?:[1-3][sp])", ":(?:G|1p)") and not ( m.group(0).find(" leur ") and morph(dDA, (m.start(2), m.group(2)), ":[NA].*:[si]", False) ) and not prevword1(s, m.start())
def c3884s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":[VR]", False, False) and not look(s[m.end():], "^ +>") and not morph(dDA, nextword1(s, m.end()), ":3s", False)
def c3892s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":V.[a-z_!?]+:(?!Y)")
def c3893s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V0e", ":Y")
def c3895s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":D", False, False)
def s3901s_1 (s, m):
    return m.group(1).replace("pin", "pain")
def c3903s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">(?:manger|dévorer|avaler|engloutir) ")
def s3903s_1 (s, m):
    return m.group(2).replace("pin", "pain")
def c3910s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">aller ", False)
def c3917s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V0e", False)
def s3917s_1 (s, m):
    return m.group(2).replace("pal", "pâl")
def s3920s_1 (s, m):
    return m.group(2).replace("pal", "pâl")
def c3926s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">prendre ", False)
def c3927s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">tirer ", False)
def c3928s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">faire ", False)
def c3930s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">prendre ", False)
def c3938s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":[NAQ]")
def c3939s_1 (s, sx, m, dDA, sCountry):
    return not prevword1(s, m.start())
def c3945s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":A") and not re.search("(?i)^seule?s?$", m.group(2))
def c3950s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V", ":(?:N|A|Q|G|MP)")
def c3963s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":(?:Y|M[12P])")
def c3966s_1 (s, sx, m, dDA, sCountry):
    return not look(s[:m.start()], "(?i)(?:peu|de) $") and morph(dDA, (m.start(2), m.group(2)), ":Y|>(tout|les?|la) ")
def c3978s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V0a", False)
def c3984s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V", ":Q")
def c3992s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, nextword1(s, m.end()), ":[AQ]", False)
def c4012s_1 (s, sx, m, dDA, sCountry):
    return not nextword1(s, m.end())
def c4015s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">résonner ", False)
def s4015s_1 (s, m):
    return m.group(1).replace("réso", "raiso")
def c4025s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":M1", False)
def s4038s_1 (s, m):
    return m.group(1).replace("sale", "salle")
def c4042s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V0e", False)
def s4042s_1 (s, m):
    return m.group(2).replace("salle", "sale")
def s4056s_1 (s, m):
    return m.group(1).replace("scep","sep")
def c4059s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">être ", False)
def s4059s_1 (s, m):
    return m.group(2).replace("sep", "scep")
def c4067s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">suivre ", False)
def c4075s_1 (s, sx, m, dDA, sCountry):
    return not look(s[m.end():], " soit ")
def c4076s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, nextword1(s, m.end()), ":[GY]", True, True) and not look(s[:m.start()], "(?i)quel(?:s|les?|) qu $|on $|il $") and not look(s[m.end():], " soit ")
def c4093s_1 (s, sx, m, dDA, sCountry):
    return ( morphex(dDA, (m.start(2), m.group(2)), ":N.*:[me]:s", ":[GW]") or (re.search("(?i)^[aeéiîou]", m.group(2)) and morphex(dDA, (m.start(2), m.group(2)), ":N.*:f:s", ":G")) ) and ( look(s[:m.start()], r"(?i)^ *$|\b(?:à|avec|chez|dès|contre|devant|derrière|en|par|pour|sans|sur) +$|, +$") or (morphex(dDA, prevword1(s, m.start()), ":V", ":(?:G|W|[NA].*:[pi])") and not look(s[:m.start()], r"(?i)\bce que?\b")) )
def s4113s_1 (s, m):
    return m.group(1).replace("sur", "sûr")
def s4116s_1 (s, m):
    return m.group(1).replace("sur", "sûr")
def c4122s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":M1", False)
def c4125s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":Y", False)
def s4125s_1 (s, m):
    return m.group(1).replace("sur", "sûr")
def c4134s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":N", ":[GMY]|>(?:fond|envergure|ampleur|importance) ")
def s4134s_1 (s, m):
    return m.group(1).replace("â", "a")
def s4138s_1 (s, m):
    return m.group(1).replace("â", "a")
def c4148s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ">aller ", False)
def c4151s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ">faire ", False)
def s4154s_1 (s, m):
    return m.group(1).replace("taule", "tôle")
def c4164s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V0e", False) and morph(dDA, (m.start(3), m.group(3)), ":Y", False)
def c4172s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">avoir ", False)
def c4197s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:[me]:s")
def c4216s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">ouvrir ", False)
def c4225s_1 (s, sx, m, dDA, sCountry):
    return not prevword1(s, m.start()) and morph(dDA, (m.start(2), m.group(2)), ":A") and not morph(dDA, nextword1(s, m.end()), ":D", False, False)
def c4254s_1 (s, sx, m, dDA, sCountry):
    return not m.group(1).isdigit() and not m.group(2).isdigit() and not morph(dDA, (m.start(0), m.group(0)), ":", False) and not morph(dDA, (m.start(2), m.group(2)), ":G", False) and _oDict.isValid(m.group(1)+m.group(2))
def c4254s_2 (s, sx, m, dDA, sCountry):
    return m.group(2) != u"là" and not re.search("(?i)^(?:ex|mi|quasi|semi|non|demi|pro|anti|multi|pseudo|proto|extra)$", m.group(1)) and not m.group(1).isdigit() and not m.group(2).isdigit() and not morph(dDA, (m.start(2), m.group(2)), ":G", False) and not morph(dDA, (m.start(0), m.group(0)), ":", False) and not _oDict.isValid(m.group(1)+m.group(2))
def c4267s_1 (s, sx, m, dDA, sCountry):
    return look(s[:m.start()], r"[\w,] +$")
def s4267s_1 (s, m):
    return m.group(0).lower()
def c4272s_1 (s, sx, m, dDA, sCountry):
    return look(s[:m.start()], r"[\w,] +$") and not( ( m.group(0)=="Juillet" and look(s[:m.start()], "(?i)monarchie +de +$") ) or ( m.group(0)=="Octobre" and look(s[:m.start()], "(?i)révolution +d’$") ) )
def s4272s_1 (s, m):
    return m.group(0).lower()
def c4291s_1 (s, sx, m, dDA, sCountry):
    return not re.search("(?i)^fonctions? ", m.group(0)) or not look(s[:m.start()], r"(?i)\ben $")
def c4298s_1 (s, sx, m, dDA, sCountry):
    return m.group(2).istitle() and morphex(dDA, (m.start(1), m.group(1)), ":N", ":(?:A|V0e|D|R|B)") and not re.search("(?i)^[oO]céan Indien", m.group(0))
def s4298s_1 (s, m):
    return m.group(2).lower()
def c4298s_2 (s, sx, m, dDA, sCountry):
    return m.group(2).islower() and not m.group(2).startswith("canadienne") and ( re.search("(?i)^(?:certaine?s?|cette|ce[ts]?|[dl]es|[nv]os|quelques|plusieurs|chaque|une)$", m.group(1)) or ( re.search("(?i)^un$", m.group(1)) and not look(s[m.end():], "(?:approximatif|correct|courant|parfait|facile|aisé|impeccable|incompréhensible)") ) )
def s4298s_2 (s, m):
    return m.group(2).capitalize()
def s4312s_1 (s, m):
    return m.group(1).capitalize()
def c4316s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">(?:parler|cours|leçon|apprendre|étudier|traduire|enseigner|professeur|enseignant|dictionnaire|méthode) ", False)
def s4316s_1 (s, m):
    return m.group(2).lower()
def s4321s_1 (s, m):
    return m.group(1).lower()
def c4333s_1 (s, sx, m, dDA, sCountry):
    return not prevword1(s, m.start())
def c4345s_1 (s, sx, m, dDA, sCountry):
    return look(s[:m.start()], r"\w")
def s4356s_1 (s, m):
    return m.group(1).capitalize()
def s4358s_1 (s, m):
    return m.group(1).capitalize()
def c4366s_1 (s, sx, m, dDA, sCountry):
    return re.search("^(?:Mètre|Watt|Gramme|Seconde|Ampère|Kelvin|Mole|Cand[eé]la|Hertz|Henry|Newton|Pascal|Joule|Coulomb|Volt|Ohm|Farad|Tesla|W[eé]ber|Radian|Stéradian|Lumen|Lux|Becquerel|Gray|Sievert|Siemens|Katal)s?|(?:Exa|P[ée]ta|Téra|Giga|Méga|Kilo|Hecto|Déc[ai]|Centi|Mi(?:lli|cro)|Nano|Pico|Femto|Atto|Ze(?:pto|tta)|Yo(?:cto|etta))(?:mètre|watt|gramme|seconde|ampère|kelvin|mole|cand[eé]la|hertz|henry|newton|pascal|joule|coulomb|volt|ohm|farad|tesla|w[eé]ber|radian|stéradian|lumen|lux|becquerel|gray|sievert|siemens|katal)s?", m.group(2))
def s4366s_1 (s, m):
    return m.group(2).lower()
def c4393s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, (m.start(1), m.group(1)), ":Y", False)
def c4395s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V1") and not look(s[:m.start()], r"(?i)\b(?:quelqu(?:e chose|’une?)|(?:l(es?|a)|nous|vous|me|te|se)[ @]trait|personne|rien(?: +[a-zéèêâîûù]+|) +$)")
def s4395s_1 (s, m):
    return suggVerbInfi(m.group(1))
def c4398s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V1", ":M[12P]")
def s4398s_1 (s, m):
    return suggVerbInfi(m.group(1))
def c4400s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V1", False)
def s4400s_1 (s, m):
    return suggVerbInfi(m.group(1))
def c4402s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V", ":[123][sp]")
def c4404s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V1", ":[NM]") and not morph(dDA, prevword1(s, m.start()), ">(?:tenir|passer) ", False)
def s4404s_1 (s, m):
    return suggVerbInfi(m.group(1))
def c4407s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V1", False)
def s4407s_1 (s, m):
    return suggVerbInfi(m.group(1))
def c4409s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V1", ":[NM]")
def s4409s_1 (s, m):
    return suggVerbInfi(m.group(1))
def c4411s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":Q", False)
def c4413s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":(?:Q|2p)", False)
def s4413s_1 (s, m):
    return suggVerbInfi(m.group(1))
def c4415s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":Q", False) and not morph(dDA, prevword1(s, m.start()), "V0.*[12]p", False)
def c4417s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">(?:devoir|savoir|pouvoir) ", False) and morphex(dDA, (m.start(2), m.group(2)), ":(?:Q|A|[13]s|2[sp])", ":[GYW]")
def s4417s_1 (s, m):
    return suggVerbInfi(m.group(2))
def c4420s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":(?:Q|A|[13]s|2[sp])", ":[GYWM]")
def s4420s_1 (s, m):
    return suggVerbInfi(m.group(1))
def s4429s_1 (s, m):
    return m.group(1)[:-1]
def c4455s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V", False)
def c4459s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">sembler ", False)
def c4473s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":[NAQ]", False) and isEndOfNG(dDA, s[m.end():], m.end())
def c4476s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V[123]_i_._") and isEndOfNG(dDA, s[m.end():], m.end())
def c4478s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":A", False) and morphex(dDA, (m.start(2), m.group(2)), ":A", ":[GM]")
def c4480s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":A", False)
def c4482s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:s", False) and morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:s", ":[GV]") and isEndOfNG(dDA, s[m.end():], m.end())
def c4484s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":N", ":[GY]") and isEndOfNG(dDA, s[m.end():], m.end())
def c4487s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":[NAQ]", ":V0") and morphex(dDA, (m.start(2), m.group(2)), ":[NAQ]", ":(?:G|[123][sp]|P)")
def c4498s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":[NAQ]", False) and isEndOfNG(dDA, s[m.end():], m.end())
def c4502s_1 (s, sx, m, dDA, sCountry):
    return not look(s[:m.start()], "[jn]’$")
def c4510s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":[NAQ]", ":G") and isEndOfNG(dDA, s[m.end():], m.end())
def c4513s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":[NAQ]", False) and isEndOfNG(dDA, s[m.end():], m.end())
def c4516s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":[NAQ]", False) and isEndOfNG(dDA, s[m.end():], m.end())
def c4520s_1 (s, sx, m, dDA, sCountry):
    return not prevword1(s, m.start())
def c4523s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":N", ":[GY]") and isEndOfNG(dDA, s[m.end():], m.end())
def c4525s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":[NAQ]", False) and isEndOfNG(dDA, s[m.end():], m.end())
def c4527s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":[NAQ]", ":Y") and isEndOfNG(dDA, s[m.end():], m.end())
def c4559s_1 (s, sx, m, dDA, sCountry):
    return re.search("(?i)^(?:fini|terminé)s?", m.group(2)) and morph(dDA, prevword1(s, m.start()), ":C", False, True)
def c4559s_2 (s, sx, m, dDA, sCountry):
    return re.search("(?i)^(?:assez|trop)$", m.group(2)) and (look(s[m.end():], "^ +d(?:e |’)") or not nextword1(s, m.end()))
def c4559s_3 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":A", ":[GVW]") and morph(dDA, prevword1(s, m.start()), ":C", False, True)
def c4571s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">aller", False) and not look(s[m.end():], " soit ")
def c4579s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V", False)
def s4579s_1 (s, m):
    return suggVerbInfi(m.group(1))
def c4581s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V", False)
def s4581s_1 (s, m):
    return suggVerbInfi(m.group(1))
def c4583s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V", False)
def s4583s_1 (s, m):
    return suggVerbInfi(m.group(1))
def c4586s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">(?:faire|vouloir) ", False) and not look(s[:m.start()], r"(?i)\b(?:en|[mtsld]es?|[nv]ous|un) +$") and morphex(dDA, (m.start(2), m.group(2)), ":V", ":M")
def s4586s_1 (s, m):
    return suggVerbInfi(m.group(2))
def c4589s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">savoir :V", False) and morph(dDA, (m.start(2), m.group(2)), ":V", False) and not look(s[:m.start()], r"(?i)\b(?:[mts]e|[vn]ous|les?|la|un) +$")
def s4589s_1 (s, m):
    return suggVerbInfi(m.group(2))
def c4592s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":(?:Q|2p)", False)
def s4592s_1 (s, m):
    return suggVerbInfi(m.group(1))
def c4595s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":(?:Q|2p)", ":N")
def s4595s_1 (s, m):
    return suggVerbInfi(m.group(1))
def c4639s_1 (s, sx, m, dDA, sCountry):
    return (morph(dDA, (m.start(2), m.group(2)), ">(?:être|sembler|devenir|re(?:ster|devenir)|para[îi]tre) ", False) or m.group(2).endswith(" été")) and morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:p", ":[GWYsi]")
def s4639s_1 (s, m):
    return suggSing(m.group(3))
def c4643s_1 (s, sx, m, dDA, sCountry):
    return (morph(dDA, (m.start(1), m.group(1)), ">(?:être|sembler|devenir|re(?:ster|devenir)|para[îi]tre) ", False) or m.group(1).endswith(" été")) and morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:p", ":[GWYsi]")
def s4643s_1 (s, m):
    return suggSing(m.group(2))
def c4647s_1 (s, sx, m, dDA, sCountry):
    return (morph(dDA, (m.start(2), m.group(2)), ">(?:être|sembler|devenir|re(?:ster|devenir)|para[îi]tre) ", False) or m.group(2).endswith(" été")) and (morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:p", ":[GWYsi]") or morphex(dDA, (m.start(3), m.group(3)), ":[AQ].*:f", ":[GWYme]"))
def s4647s_1 (s, m):
    return suggMasSing(m.group(3))
def c4652s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":[NAQ].*:p", ":[GWYsi]") or ( morphex(dDA, (m.start(1), m.group(1)), ":[AQ].*:f", ":[GWYme]") and not morph(dDA, nextword1(s, m.end()), ":N.*:f", False, False) )
def s4652s_1 (s, m):
    return suggMasSing(m.group(1))
def c4656s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":[NAQ].*:p", ":[GWYsi]") or ( morphex(dDA, (m.start(1), m.group(1)), ":[AQ].*:f", ":[GWYme]") and not morph(dDA, nextword1(s, m.end()), ":N.*:f", False, False) )
def s4656s_1 (s, m):
    return suggMasSing(m.group(1))
def c4660s_1 (s, sx, m, dDA, sCountry):
    return (morph(dDA, (m.start(2), m.group(2)), ">(?:être|sembler|devenir|re(?:ster|devenir)|para[îi]tre) ", False) or m.group(2).endswith(" été")) and (morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:p", ":[GWYsi]") or morphex(dDA, (m.start(3), m.group(3)), ":[AQ].*:f", ":[GWYme]")) and not morph(dDA, prevword1(s, m.start()), ":R", False, False)
def s4660s_1 (s, m):
    return suggMasSing(m.group(3))
def c4666s_1 (s, sx, m, dDA, sCountry):
    return (morph(dDA, (m.start(2), m.group(2)), ">(?:être|sembler|devenir|re(?:ster|devenir)|para[îi]tre) ", False) or m.group(2).endswith(" été")) and (morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:p", ":[GWYsi]") or morphex(dDA, (m.start(3), m.group(3)), ":[AQ].*:m", ":[GWYfe]")) and not morph(dDA, prevword1(s, m.start()), ":R|>de ", False, False)
def s4666s_1 (s, m):
    return suggFemSing(m.group(3))
def c4672s_1 (s, sx, m, dDA, sCountry):
    return (morph(dDA, (m.start(2), m.group(2)), ">(?:être|sembler|devenir|re(?:ster|devenir)|para[îi]tre) ", False) or m.group(2).endswith(" été")) and (morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:p", ":[GWYsi]") or morphex(dDA, (m.start(3), m.group(3)), ":[AQ].*:m", ":[GWYfe]"))
def s4672s_1 (s, m):
    return suggFemSing(m.group(3))
def c4677s_1 (s, sx, m, dDA, sCountry):
    return not re.search("(?i)^légion$", m.group(2)) and not look(s[:m.start()], r"(?i)\b(?:nous|ne) +$") and ((morph(dDA, (m.start(1), m.group(1)), ">(?:être|sembler|devenir|re(?:ster|devenir)|para[îi]tre) ", False) and morph(dDA, (m.start(1), m.group(1)), ":1p", False)) or m.group(1).endswith(" été")) and morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:s", ":[GWYpi]")
def s4677s_1 (s, m):
    return suggPlur(m.group(2))
def c4683s_1 (s, sx, m, dDA, sCountry):
    return not re.search("(?i)^légion$", m.group(3)) and (morph(dDA, (m.start(2), m.group(2)), ">(?:être|sembler|devenir|re(?:ster|devenir)|para[îi]tre) ", False) or m.group(2).endswith(" été")) and (morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:s", ":[GWYpi]") or morphex(dDA, (m.start(3), m.group(3)), ":[AQ].*:f", ":[GWYme]")) and not look(s[:m.start()], "(?i)ce que? +$") and (not re.search("^(?:ceux-(?:ci|là)|lesquels)$", m.group(1)) or not morph(dDA, prevword1(s, m.start()), ":R", False, False))
def s4683s_1 (s, m):
    return suggMasPlur(m.group(3))
def c4689s_1 (s, sx, m, dDA, sCountry):
    return not re.search("(?i)^légion$", m.group(3)) and (morph(dDA, (m.start(2), m.group(2)), ">(?:être|sembler|devenir|re(?:ster|devenir)|para[îi]tre) ", False) or m.group(2).endswith(" été")) and (morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:s", ":[GWYpi]") or morphex(dDA, (m.start(3), m.group(3)), ":[AQ].*:m", ":[GWYfe]")) and (not re.search("(?i)^(?:elles|celles-(?:ci|là)|lesquelles)$", m.group(1)) or not morph(dDA, prevword1(s, m.start()), ":R", False, False))
def s4689s_1 (s, m):
    return suggFemPlur(m.group(3))
def c4695s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">avoir ", False) and morphex(dDA, (m.start(2), m.group(2)), ":[123]s", ":[GNAQWY]")
def s4695s_1 (s, m):
    return suggVerbPpas(m.group(2))
def c4776s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ">(?:sembler|para[îi]tre|pouvoir|penser|préférer|croire|d(?:evoir|éclarer|ésirer|étester|ire)|vouloir|affirmer|aimer|adorer|souhaiter|estimer|imaginer) ", False) and morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:p", ":[GWYsi]")
def s4776s_1 (s, m):
    return suggSing(m.group(3))
def c4780s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">(?:sembler|para[îi]tre|pouvoir|penser|préférer|croire|d(?:evoir|éclarer|ésirer|étester|ire)|vouloir|affirmer|aimer|adorer|souhaiter|estimer|imaginer) ", False) and morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:p", ":[GWYsi]")
def s4780s_1 (s, m):
    return suggSing(m.group(2))
def c4784s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ">(?:sembler|para[îi]tre|pouvoir|penser|préférer|croire|d(?:evoir|éclarer|ésirer|étester|ire)|vouloir|affirmer|aimer|adorer|souhaiter|estimer|imaginer) ", False) and (morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:p", ":[GWYsi]") or morphex(dDA, (m.start(3), m.group(3)), ":[AQ].*:f", ":[GWYme]"))
def s4784s_1 (s, m):
    return suggMasSing(m.group(3))
def c4789s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ">(?:sembler|para[îi]tre|pouvoir|penser|préférer|croire|d(?:evoir|éclarer|ésirer|étester|ire)|vouloir|affirmer|aimer|adorer|souhaiter|estimer|imaginer) ", False) and (morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:p", ":[MWYsi]") or morphex(dDA, (m.start(3), m.group(3)), ":[AQ].*:f", ":[GWYme]")) and not morph(dDA, prevword1(s, m.start()), ":R", False, False)
def s4789s_1 (s, m):
    return suggMasSing(m.group(3))
def c4795s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ">(?:sembler|para[îi]tre|pouvoir|penser|préférer|croire|d(?:evoir|éclarer|ésirer|étester|ire)|vouloir|affirmer|aimer|adorer|souhaiter|estimer|imaginer) ", False) and (morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:p", ":[GWYsi]") or morphex(dDA, (m.start(3), m.group(3)), ":[AQ].*:m", ":[GWYfe]")) and not morph(dDA, prevword1(s, m.start()), ":R", False, False)
def s4795s_1 (s, m):
    return suggFemSing(m.group(3))
def c4801s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ">(?:sembler|para[îi]tre|pouvoir|penser|préférer|croire|d(?:evoir|éclarer|ésirer|étester|ire)|vouloir|affirmer|aimer|adorer|souhaiter|estimer|imaginer) ", False) and (morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:p", ":[MWYsi]") or morphex(dDA, (m.start(3), m.group(3)), ":[AQ].*:m", ":[GWYfe]"))
def s4801s_1 (s, m):
    return suggFemSing(m.group(3))
def c4806s_1 (s, sx, m, dDA, sCountry):
    return not re.search("(?i)^légion$", m.group(2)) and morph(dDA, (m.start(1), m.group(1)), ">(?:sembler|para[îi]tre|pouvoir|penser|préférer|croire|d(?:evoir|éclarer|ésirer|étester|ire)|vouloir|affirmer|aimer|adorer|souhaiter|estimer|imaginer) ", False) and morph(dDA, (m.start(1), m.group(1)), ":1p", False) and morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:s", ":[GWYpi]")
def s4806s_1 (s, m):
    return suggPlur(m.group(2))
def c4811s_1 (s, sx, m, dDA, sCountry):
    return not re.search("(?i)^légion$", m.group(3)) and morph(dDA, (m.start(2), m.group(2)), ">(?:sembler|para[îi]tre|pouvoir|penser|préférer|croire|d(?:evoir|éclarer|ésirer|étester|ire)|vouloir|affirmer|aimer|adorer|souhaiter|estimer|imaginer) ", False) and (morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:s", ":[GWYpi]") or morphex(dDA, (m.start(3), m.group(3)), ":[AQ].*:f", ":[GWYme]")) and (not re.search("^(?:ceux-(?:ci|là)|lesquels)$", m.group(1)) or not morph(dDA, prevword1(s, m.start()), ":R", False, False))
def s4811s_1 (s, m):
    return suggMasPlur(m.group(3))
def c4817s_1 (s, sx, m, dDA, sCountry):
    return not re.search("(?i)^légion$", m.group(3)) and morph(dDA, (m.start(2), m.group(2)), ">(?:sembler|para[îi]tre|pouvoir|penser|préférer|croire|d(?:evoir|éclarer|ésirer|étester|ire)|vouloir|affirmer|aimer|adorer|souhaiter|estimer|imaginer) ", False) and (morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:s", ":[GWYpi]") or morphex(dDA, (m.start(3), m.group(3)), ":[AQ].*:m", ":[GWYfe]")) and (not re.search("^(?:elles|celles-(?:ci|là)|lesquelles)$", m.group(1)) or not morph(dDA, prevword1(s, m.start()), ":R", False, False))
def s4817s_1 (s, m):
    return suggFemPlur(m.group(3))
def c4848s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:p", ":[GMWYsi]") and not morph(dDA, (m.start(1), m.group(1)), ":G", False)
def s4848s_1 (s, m):
    return suggSing(m.group(2))
def c4852s_1 (s, sx, m, dDA, sCountry):
    return not re.search("(?i)^légion$", m.group(2)) and morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:s", ":[GWYpi]") and not morph(dDA, (m.start(1), m.group(1)), ":G", False)
def s4852s_1 (s, m):
    return suggPlur(m.group(2))
def c4857s_1 (s, sx, m, dDA, sCountry):
    return not re.search("(?i)^légion$", m.group(3)) and ((morphex(dDA, (m.start(3), m.group(3)), ":[AQ].*:f", ":[GWme]") and morphex(dDA, (m.start(2), m.group(2)), ":m", ":[Gfe]")) or (morphex(dDA, (m.start(3), m.group(3)), ":[AQ].*:m", ":[GWfe]") and morphex(dDA, (m.start(2), m.group(2)), ":f", ":[Gme]"))) and not ( morph(dDA, (m.start(3), m.group(3)), ":p", False) and morph(dDA, (m.start(2), m.group(2)), ":s", False) ) and not morph(dDA, prevword1(s, m.start()), ":(?:R|P|Q|Y|[123][sp])", False, False) and not look(s[:m.start()], r"\b(?:et|ou|de) +$")
def s4857s_1 (s, m):
    return switchGender(m.group(3))
def c4864s_1 (s, sx, m, dDA, sCountry):
    return not re.search("(?i)^légion$", m.group(2)) and ((morphex(dDA, (m.start(1), m.group(1)), ":M[1P].*:f", ":[GWme]") and morphex(dDA, (m.start(2), m.group(2)), ":m", ":[GWfe]")) or (morphex(dDA, (m.start(1), m.group(1)), ":M[1P].*:m", ":[GWfe]") and morphex(dDA, (m.start(2), m.group(2)), ":f", ":[GWme]"))) and not morph(dDA, prevword1(s, m.start()), ":(?:R|P|Q|Y|[123][sp])", False, False) and not look(s[:m.start()], r"\b(?:et|ou|de) +$")
def s4864s_1 (s, m):
    return switchGender(m.group(2))
def c4873s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":A.*:p", ":(?:G|E|M1|W|s|i)")
def s4873s_1 (s, m):
    return suggSing(m.group(1))
def c4877s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":A.*:[fp]", ":(?:G|E|M1|W|m:[si])")
def s4877s_1 (s, m):
    return suggMasSing(m.group(1))
def c4881s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":A.*:[mp]", ":(?:G|E|M1|W|f:[si])|>(?:désoler|pire) ")
def s4881s_1 (s, m):
    return suggFemSing(m.group(1))
def c4885s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":A.*:[fs]", ":(?:G|E|M1|W|m:[pi])|>(?:désoler|pire) ")
def s4885s_1 (s, m):
    return suggMasPlur(m.group(1))
def c4889s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":A.*:[ms]", ":(?:G|E|M1|W|f:[pi])|>(?:désoler|pire) ")
def s4889s_1 (s, m):
    return suggFemPlur(m.group(1))
def c4906s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), "V0e", False)
def c4913s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":(?:[123][sp]|Y|[NAQ].*:p)", ":[GWsi]")
def s4913s_1 (s, m):
    return suggSing(m.group(1))
def c4916s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":(?:[123][sp]|Y|[NAQ].*:p)", ":[GWsi]")
def s4916s_1 (s, m):
    return suggSing(m.group(1))
def c4919s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":(?:[123][sp]|Y|[NAQ].*:[pf])", ":(?:G|W|[me]:[si])") and not (m.group(1) == "ce" and morph(dDA, (m.start(2), m.group(2)), ":Y", False))
def s4919s_1 (s, m):
    return suggMasSing(m.group(2))
def c4922s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":(?:[123][sp]|Y|[NAQ].*:[pm])", ":(?:G|W|[fe]:[si])")
def s4922s_1 (s, m):
    return suggFemSing(m.group(1))
def c4925s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":(?:[123][sp]|Y|[NAQ].*:s)", ":[GWpi]")
def s4925s_1 (s, m):
    return suggPlur(m.group(1))
def c4928s_1 (s, sx, m, dDA, sCountry):
    return not re.search("(?i)^légion$", m.group(1)) and (morphex(dDA, (m.start(1), m.group(1)), ":(?:[123][sp]|Y|[NAQ].*:s)", ":[GWpi]") or morphex(dDA, (m.start(1), m.group(1)), ":(?:[123][sp]|[AQ].*:f)", ":[GWme]"))
def s4928s_1 (s, m):
    return suggMasPlur(m.group(1))
def c4931s_1 (s, sx, m, dDA, sCountry):
    return not re.search("(?i)^légion$", m.group(1)) and (morphex(dDA, (m.start(1), m.group(1)), ":(?:[123][sp]|Y|[NAQ].*:s)", ":[GWpi]") or morphex(dDA, (m.start(1), m.group(1)), ":(?:[123][sp]|[AQ].*:m)", ":[GWfe]"))
def s4931s_1 (s, m):
    return suggFemPlur(m.group(1))
def c4960s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":[NAQ]", ":[QWGBMpi]") and not re.search("(?i)^(?:légion|nombre|cause)$", m.group(1)) and not look(s[:m.start()], r"(?i)\bce que?\b")
def s4960s_1 (s, m):
    return suggPlur(m.group(1))
def c4960s_2 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V", ":(?:N|A|Q|W|G|3p)") and not look(s[:m.start()], r"(?i)\bce que?\b")
def s4960s_2 (s, m):
    return suggVerbPpas(m.group(1), ":m:p")
def c4971s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">(?:montrer|penser|révéler|savoir|sentir|voir|vouloir) ", False) and morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:p", ":[GWsi]")
def s4971s_1 (s, m):
    return suggSing(m.group(2))
def c4975s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">(?:montrer|penser|révéler|savoir|sentir|voir|vouloir) ", False) and morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:p", ":[GWsi]")
def s4975s_1 (s, m):
    return suggSing(m.group(2))
def c4979s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ">(?:montrer|penser|révéler|savoir|sentir|voir|vouloir) ", False) and (morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:p", ":[GWsi]") or morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:f", ":[GWme]")) and (not re.search("^(?:celui-(?:ci|là)|lequel)$", m.group(1)) or not morph(dDA, prevword1(s, m.start()), ":R", False, False))
def s4979s_1 (s, m):
    return suggMasSing(m.group(3))
def c4985s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ">(?:montrer|penser|révéler|savoir|sentir|voir|vouloir) ", False) and (morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:p", ":[GWsi]") or morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:m", ":[GWfe]")) and not morph(dDA, prevword1(s, m.start()), ":R", False, False)
def s4985s_1 (s, m):
    return suggFemSing(m.group(3))
def c4991s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ">(?:montrer|penser|révéler|savoir|sentir|voir|vouloir) ", False) and (morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:p", ":[GWsi]") or morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:m", ":[GWfe]"))
def s4991s_1 (s, m):
    return suggFemSing(m.group(3))
def c4996s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">(?:montrer|penser|révéler|savoir|sentir|voir|vouloir) ", False) and morphex(dDA, (m.start(2), m.group(2)), ":[NAQ].*:s", ":[GWpi]")
def s4996s_1 (s, m):
    return suggPlur(m.group(2))
def c5000s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ">(?:montrer|penser|révéler|savoir|sentir|voir|vouloir) ", False) and (morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:s", ":[GWpi]") or morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:f", ":[GWme]")) and (not re.search("^(?:ceux-(?:ci|là)|lesquels)$", m.group(1)) or not morph(dDA, prevword1(s, m.start()), ":R", False, False))
def s5000s_1 (s, m):
    return suggMasPlur(m.group(3))
def c5006s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ">(?:montrer|penser|révéler|savoir|sentir|voir|vouloir) ", False) and (morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:s", ":[GWpi]") or morphex(dDA, (m.start(3), m.group(3)), ":[NAQ].*:m", ":[GWfe]")) and (not re.search("^(?:elles|celles-(?:ci|là)|lesquelles)$", m.group(1)) or not morph(dDA, prevword1(s, m.start()), ":R", False, False))
def s5006s_1 (s, m):
    return suggFemPlur(m.group(3))
def c5014s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">(?:trouver|considérer|croire) ", False) and morphex(dDA, (m.start(2), m.group(2)), ":[AQ]:(?:m:p|f)", ":(?:G|[AQ]:m:[is])")
def s5014s_1 (s, m):
    return suggMasSing(m.group(2))
def c5017s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">(?:trouver|considérer|croire) ", False) and morphex(dDA, (m.start(2), m.group(2)), ":[AQ]:(?:f:p|m)", ":(?:G|[AQ]:f:[is])")
def s5017s_1 (s, m):
    return suggFemSing(m.group(2))
def c5020s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">(?:trouver|considérer|croire) ", False) and morphex(dDA, (m.start(2), m.group(2)), ":[AQ].*:s", ":(?:G|[AQ].*:[ip])")
def s5020s_1 (s, m):
    return suggPlur(m.group(2))
def c5023s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ">(?:trouver|considérer|croire) ", False) and morphex(dDA, (m.start(3), m.group(3)), ":[AQ].*:p", ":(?:G|[AQ].*:[is])")
def s5023s_1 (s, m):
    return suggSing(m.group(3))
def c5026s_1 (s, sx, m, dDA, sCountry):
    return ( morphex(dDA, (m.start(1), m.group(1)), ">(?:trouver|considérer|croire) ", ":1p") or (morph(dDA, (m.start(1), m.group(1)), ">(?:trouver|considérer|croire) .*:1p", False) and look(s[:m.start()], r"\bn(?:ous|e) +$")) ) and morphex(dDA, (m.start(2), m.group(2)), ":[AQ].*:s", ":(?:G|[AQ].*:[ip])")
def s5026s_1 (s, m):
    return suggPlur(m.group(2))
def c5048s_1 (s, sx, m, dDA, sCountry):
    return not re.search("(?i)^(?:confiance|cours|envie|peine|prise|crainte|cure|affaire|hâte|force|recours)$", m.group(3)) and morph(dDA, (m.start(2), m.group(2)), ":V0a", False) and morphex(dDA, (m.start(3), m.group(3)), ":(?:[123][sp]|Q.*:[fp])", ":(?:G|W|Q.*:m:[si])")
def s5048s_1 (s, m):
    return suggMasSing(m.group(3))
def c5054s_1 (s, sx, m, dDA, sCountry):
    return not re.search("(?i)^(?:confiance|cours|envie|peine|prise|crainte|cure|affaire|hâte|force|recours)$", m.group(4)) and morph(dDA, (m.start(3), m.group(3)), ":V0a", False) and morphex(dDA, (m.start(4), m.group(4)), ":(?:[123][sp]|Q.*:[fp])", ":(?:G|W|Q.*:m:[si])")
def s5054s_1 (s, m):
    return suggMasSing(m.group(4))
def c5060s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V0a", False) and morphex(dDA, (m.start(2), m.group(2)), ":V[0-3]..t.*:Q.*:s", ":[GWpi]") and not morph(dDA, nextword1(s, m.end()), ":V", False)
def s5060s_1 (s, m):
    return suggPlur(m.group(2))
def c5065s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V0a", False) and morphex(dDA, (m.start(2), m.group(2)), ":V[0-3]..t_.*:Q.*:s", ":[GWpi]") and not look(s[:m.start()], r"\bque?\b")
def s5065s_1 (s, m):
    return suggPlur(m.group(2))
def c5070s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V0a", False) and morphex(dDA, (m.start(2), m.group(2)), ":V[0-3]..t.*:Q.*:p", ":[GWsi]") and not morph(dDA, nextword1(s, m.end()), ":V", False)
def s5070s_1 (s, m):
    return m.group(2)[:-1]
def c5075s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":V0a", False) and morphex(dDA, (m.start(3), m.group(3)), ":V[0-3]..t_.*:Q.*:p", ":[GWsi]") and not look(s[:m.start()], r"\bque?\b") and not morph(dDA, nextword1(s, m.end()), ":V", False)
def s5075s_1 (s, m):
    return m.group(3)[:-1]
def c5080s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":Q.*:(?:f|m:p)", ":m:[si]")
def s5080s_1 (s, m):
    return suggMasSing(m.group(1))
def c5086s_1 (s, sx, m, dDA, sCountry):
    return not re.search("(?i)^(?:confiance|cours|envie|peine|prise|crainte|cure|affaire|hâte|force|recours)$", m.group(1)) and morphex(dDA, (m.start(1), m.group(1)), ":Q.*:(?:f|m:p)", ":m:[si]") and look(s[:m.start()], "(?i)(?:après +$|sans +$|pour +$|que? +$|quand +$|, +$|^ *$)")
def s5086s_1 (s, m):
    return suggMasSing(m.group(1))
def c5116s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(3), m.group(3)), ":V0a", False) and not (re.search("^(?:décidé|essayé|tenté)$", m.group(4)) and look(s[m.end():], " +d(?:e |’)")) and morph(dDA, (m.start(2), m.group(2)), ":[NAQ]", False) and morphex(dDA, (m.start(4), m.group(4)), ":V[0-3]..t.*:Q.*:s", ":[GWpi]") and not morph(dDA, nextword1(s, m.end()), ":(?:Y|Oo)", False)
def s5116s_1 (s, m):
    return suggPlur(m.group(4), m.group(2))
def c5124s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(3), m.group(3)), ":V0a", False) and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:m", False) and (morphex(dDA, (m.start(4), m.group(4)), ":V[0-3]..t.*:Q.*:f", ":[GWme]") or morphex(dDA, (m.start(4), m.group(4)), ":V[0-3]..t.*:Q.*:p", ":[GWsi]"))
def s5124s_1 (s, m):
    return suggMasSing(m.group(4))
def c5131s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(3), m.group(3)), ":V0a", False) and not (re.search("^(?:décidé|essayé|tenté)$", m.group(4)) and look(s[m.end():], " +d(?:e |’)")) and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:f", False) and (morphex(dDA, (m.start(4), m.group(4)), ":V[0-3]..t.*:Q.*:m", ":[GWfe]") or morphex(dDA, (m.start(4), m.group(4)), ":V[0-3]..t.*:Q.*:p", ":[GWsi]")) and not morph(dDA, nextword1(s, m.end()), ":(?:Y|Oo)|>que?", False)
def s5131s_1 (s, m):
    return suggFemSing(m.group(4))
def c5151s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V0a", False) and (morphex(dDA, (m.start(2), m.group(2)), ":V[0-3]..t.*:Q.*:f", ":[GWme]") or morphex(dDA, (m.start(2), m.group(2)), ":V[0-3]..t.*:Q.*:p", ":[GWsi]"))
def s5151s_1 (s, m):
    return suggMasSing(m.group(2))
def c5157s_1 (s, sx, m, dDA, sCountry):
    return not re.search("^(?:A|avions)$", m.group(1)) and morph(dDA, (m.start(1), m.group(1)), ":V0a", False) and morph(dDA, (m.start(2), m.group(2)), ":V.+:(?:Y|2p)", False)
def s5157s_1 (s, m):
    return suggVerbPpas(m.group(2), ":m:s")
def c5163s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V0a", False) and (morph(dDA, (m.start(3), m.group(3)), ":Y") or re.search("^(?:[mtsn]e|[nv]ous|leur|lui)$", m.group(3)))
def c5167s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V0a", False) and (morph(dDA, (m.start(3), m.group(3)), ":Y") or re.search("^(?:[mtsn]e|[nv]ous|leur|lui)$", m.group(3)))
def c5173s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, nextword1(s, m.end()), ":[NAQ].*:[me]", False)
def c5175s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V0e", False)
def c5192s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V0a", False) and morphex(dDA, (m.start(2), m.group(2)), ":(?:Y|2p|Q.*:[fp])", ":m:[si]") and m.group(2) != "prise" and not morph(dDA, prevword1(s, m.start()), ">(?:les|[nv]ous|en)|:[NAQ].*:[fp]", False) and not look(s[:m.start()], r"(?i)\bquel(?:le|)s?\b")
def s5192s_1 (s, m):
    return suggMasSing(m.group(2))
def c5198s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":V0a", False) and morphex(dDA, (m.start(3), m.group(3)), ":(?:Y|2p|Q.*:p)", ":[si]")
def s5198s_1 (s, m):
    return suggMasSing(m.group(3))
def c5203s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V0a", False) and morphex(dDA, (m.start(2), m.group(2)), ":V[123]..t.* :Q.*:s", ":[GWpi]")
def s5203s_1 (s, m):
    return suggPlur(m.group(2))
def c5209s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V", ":(?:G|Y|P|1p|3[sp])") and not look(s[m.end():], "^ +(?:je|tu|ils?|elles?|on|[vn]ous) ")
def s5209s_1 (s, m):
    return suggVerb(m.group(1), ":1p")
def c5215s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V", ":(?:G|Y|P|2p|3[sp])") and not look(s[m.end():], "^ +(?:je|ils?|elles?|on|[vn]ous) ")
def s5215s_1 (s, m):
    return suggVerb(m.group(1), ":2p")
def c5252s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[NAQ]", ":G")
def c5260s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V[13].*:Ip.*:2s", ":[GNA]")
def s5260s_1 (s, m):
    return m.group(1)[:-1]
def c5263s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V[13].*:Ip.*:2s", ":G")
def s5263s_1 (s, m):
    return m.group(1)[:-1]
def c5268s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":[MOs]")
def c5271s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V[23].*:Ip.*:3s", ":[GNA]") and analyse(m.group(1)[:-1]+"s", ":E:2s", False) and not re.search("(?i)^doit$", m.group(1)) and not (re.search("(?i)^vient$", m.group(1)) and look(s[m.end():], " +l[ea]"))
def s5271s_1 (s, m):
    return m.group(1)[:-1]+"s"
def c5275s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V[23].*:Ip.*:3s", ":G") and analyse(m.group(1)[:-1]+"s", ":E:2s", False)
def s5275s_1 (s, m):
    return m.group(1)[:-1]+"s"
def c5280s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V3.*:Ip.*:3s", ":[GNA]")
def c5283s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V3.*:Ip.*:3s", ":G")
def c5293s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":A", ":G") and not look(s[m.end():], r"\bsoit\b")
def c5304s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, (m.start(1), m.group(1)), ":E|>chez", False) and _oDict.isValid(m.group(1))
def s5304s_1 (s, m):
    return suggVerbImpe(m.group(1))
def c5309s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, (m.start(1), m.group(1)), ":E|>chez", False) and _oDict.isValid(m.group(1))
def s5309s_1 (s, m):
    return suggVerbTense(m.group(1), ":E", ":2s")
def c5334s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":E", ":[GM]")
def c5339s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":E", ":[GM]") and morphex(dDA, nextword1(s, m.end()), ":", ":(?:Y|3[sp])", True) and morph(dDA, prevword1(s, m.start()), ":Cc", False, True) and not look(s[:m.start()], "~ +$")
def c5344s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":E", ":[GM]") and morphex(dDA, nextword1(s, m.end()), ":", ":(?:N|A|Q|Y|B|3[sp])", True) and morph(dDA, prevword1(s, m.start()), ":Cc", False, True) and not look(s[:m.start()], "~ +$")
def c5349s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":E", ":[GM]") and morphex(dDA, nextword1(s, m.end()), ":", ":(?:N|A|Q|Y|MP)", True) and morph(dDA, prevword1(s, m.start()), ":Cc", False, True) and not look(s[:m.start()], "~ +$")
def c5363s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":E", ":(?:G|M[12])") and morphex(dDA, nextword1(s, m.end()), ":", ":(?:Y|[123][sp])", True)
def s5363s_1 (s, m):
    return m.group(0).replace(" ", "-")
def c5368s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":E", False)
def s5368s_1 (s, m):
    return m.group(0).replace(" ", "-")
def c5373s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":E", False) and morphex(dDA, nextword1(s, m.end()), ":[RC]", ":[NAQ]", True)
def s5373s_1 (s, m):
    return m.group(0).replace(" ", "-")
def c5378s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":E", False) and morphex(dDA, nextword1(s, m.end()), ":[RC]", ":Y", True)
def s5378s_1 (s, m):
    return m.group(0).replace(" ", "-")
def c5384s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, nextword1(s, m.end()), ":Y", False, False)
def s5384s_1 (s, m):
    return m.group(0).replace(" ", "-")
def c5386s_1 (s, sx, m, dDA, sCountry):
    return not prevword1(s, m.start()) and not morph(dDA, nextword1(s, m.end()), ":Y", False, False)
def s5388s_1 (s, m):
    return m.group(0).replace(" ", "-")
def c5414s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":R", False, True)
def c5415s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":R", False, False)
def c5417s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":R", False, False)
def c5419s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":[123][sp]")
def c5420s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":[123]s", False, False)
def c5421s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":(?:[123]s|R)", False, False)
def c5422s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":(?:[123]p|R)", False, False)
def c5423s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, prevword1(s, m.start()), ":3p", False, False)
def c5424s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":[123][sp]", False)
def c5425s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[123][sp]", ":(?:[NAQ].*:m:[si]|G|M)")
def c5426s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[123][sp]", ":(?:[NAQ].*:f:[si]|G|M)")
def c5427s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[123][sp]", ":(?:[NAQ].*:[si]|G|M)")
def c5428s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[123][sp]", ":(?:[NAQ].*:[si]|G|M)")
def c5430s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[123][sp]", ":(?:A|G|M|1p)")
def c5431s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":[123][sp]", ":(?:A|G|M|2p)")
def c5433s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":V", False)
def c5434s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":V", False)
def c5435s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, (m.start(2), m.group(2)), ":2s", False) or look(s[:m.start()], r"(?i)\b(?:je|tu|on|ils?|elles?|nous) +$")
def c5436s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, (m.start(2), m.group(2)), ":2s|>(ils?|elles?|on) ", False) or look(s[:m.start()], r"(?i)\b(?:je|tu|on|ils?|elles?|nous) +$")
def c5450s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V", False)
def c5453s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V", ":Y")
def c5467s_1 (s, sx, m, dDA, sCountry):
    return not look(s[:m.start()], r"(?i)\b(?:ce que?|tout) ")
def c5479s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V", ":M") and not (m.group(1).endswith("ez") and look(s[m.end():], " +vous"))
def s5479s_1 (s, m):
    return suggVerbInfi(m.group(1))
def c5482s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":(?:Q|2p)", ":M")
def s5482s_1 (s, m):
    return suggVerbInfi(m.group(1))
def c5485s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">(?:aimer|aller|désirer|devoir|espérer|pouvoir|préférer|souhaiter|venir) ", False) and not morph(dDA, (m.start(1), m.group(1)), ":[GN]", False) and morphex(dDA, (m.start(2), m.group(2)), ":V", ":M")
def s5485s_1 (s, m):
    return suggVerbInfi(m.group(2))
def c5489s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">devoir ", False) and morphex(dDA, (m.start(2), m.group(2)), ":V", ":M") and not morph(dDA, prevword1(s, m.start()), ":D", False)
def s5489s_1 (s, m):
    return suggVerbInfi(m.group(2))
def c5492s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">(?:cesser|décider|défendre|suggérer|commander|essayer|tenter|choisir|permettre|interdire) ", False) and morphex(dDA, (m.start(2), m.group(2)), ":(?:Q|2p)", ":M")
def s5492s_1 (s, m):
    return suggVerbInfi(m.group(2))
def c5495s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":(?:Q|2p)", ":M")
def s5495s_1 (s, m):
    return suggVerbInfi(m.group(1))
def c5498s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">valoir ", False) and morphex(dDA, (m.start(2), m.group(2)), ":(?:Q|2p)", ":[GM]")
def s5498s_1 (s, m):
    return suggVerbInfi(m.group(2))
def c5501s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V1", ":[NM]") and not m.group(1).istitle() and not look(s[:m.start()], "> +$")
def s5501s_1 (s, m):
    return suggVerbInfi(m.group(1))
def c5504s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V1", ":N")
def s5504s_1 (s, m):
    return suggVerbInfi(m.group(2))
def c5517s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":V0e", False) and (morphex(dDA, (m.start(2), m.group(2)), ":Y", ":[NAQ]") or m.group(2) in aSHOULDBEVERB) and not re.search("(?i)^(?:soit|été)$", m.group(1)) and not morph(dDA, prevword1(s, m.start()), ":Y|>ce", False, False) and not look(s[:m.start()], "(?i)ce (?:>|qu|que >) $") and not look_chk1(dDA, s[:m.start()], 0, r"(\w[\w-]+) +> $", ":Y") and not look_chk1(dDA, s[:m.start()], 0, r"^ *>? *(\w[\w-]+)", ":Y")
def s5517s_1 (s, m):
    return suggVerbPpas(m.group(2))
def c5528s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, (m.start(1), m.group(1)), ":1s|>(?:en|y)", False)
def s5528s_1 (s, m):
    return suggVerb(m.group(1), ":1s")
def c5531s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V", ":(?:1s|G)") and not (morph(dDA, (m.start(2), m.group(2)), ":[PQ]", False) and morph(dDA, prevword1(s, m.start()), ":V0.*:1s", False, False))
def s5531s_1 (s, m):
    return suggVerb(m.group(2), ":1s")
def c5534s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V", ":(?:1s|G|1p)")
def s5534s_1 (s, m):
    return suggVerb(m.group(2), ":1s")
def c5537s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V", ":(?:1s|G|1p)")
def s5537s_1 (s, m):
    return suggVerb(m.group(2), ":1s")
def c5540s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V", ":(?:1s|G|1p|3p!)")
def s5540s_1 (s, m):
    return suggVerb(m.group(2), ":1s")
def c5560s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V", ":(?:G|[ISK].*:2s)") and not (morph(dDA, (m.start(2), m.group(2)), ":[PQ]", False) and morph(dDA, prevword1(s, m.start()), ":V0.*:2s", False, False))
def s5560s_1 (s, m):
    return suggVerb(m.group(2), ":2s")
def c5563s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V", ":(?:G|[ISK].*:2s)")
def s5563s_1 (s, m):
    return suggVerb(m.group(2), ":2s")
def c5566s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V", ":(?:G|2p|3p!|[ISK].*:2s)")
def s5566s_1 (s, m):
    return suggVerb(m.group(2), ":2s")
def c5577s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V", ":(?:3s|P|G)") and not (morph(dDA, (m.start(2), m.group(2)), ":[PQ]", False) and morph(dDA, prevword1(s, m.start()), ":V0.*:3s", False, False))
def s5577s_1 (s, m):
    return suggVerb(m.group(2), ":3s")
def c5580s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V", ":(?:3s|P|G)")
def s5580s_1 (s, m):
    return suggVerb(m.group(2), ":3s")
def c5595s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V", ":(?:N|A|3s|P|Q|G|V0e.*:3p)")
def s5595s_1 (s, m):
    return suggVerb(m.group(2), ":3s")
def c5599s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V", ":(?:3s|P|Q|G)")
def s5599s_1 (s, m):
    return suggVerb(m.group(2), ":3s")
def c5607s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V", ":(?:3s|P|Q|G|3p!)") and not morph(dDA, prevword1(s, m.start()), ":[VR]|>de", False, False) and not(m.group(1).endswith("out") and morph(dDA, (m.start(2), m.group(2)), ":Y", False))
def s5607s_1 (s, m):
    return suggVerb(m.group(2), ":3s")
def c5624s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V", ":(?:3s|P|G|3p!)") and not morph(dDA, prevword1(s, m.start()), ":R|>(?:et|ou)", False, False) and not (morph(dDA, (m.start(1), m.group(1)), ":[PQ]", False) and morph(dDA, prevword1(s, m.start()), ":V0.*:3s", False, False))
def s5624s_1 (s, m):
    return suggVerb(m.group(1), ":3s")
def c5628s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V", ":(?:3s|P|G|3p!)") and not morph(dDA, prevword1(s, m.start()), ":R|>(?:et|ou)", False, False)
def s5628s_1 (s, m):
    return suggVerb(m.group(1), ":3s")
def c5645s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":3p", ":(?:G|3s)")
def c5648s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":3s", ":(?:G|3p)")
def c5651s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":3p", ":(?:G|3s)") and (not prevword1(s, m.start()) or look(s[:m.start()], r"(?i)\b(?:parce que?|quoi ?que?|pour ?quoi|puisque?|quand|com(?:ment|bien)|car|tandis que?) +$"))
def c5655s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":3s", ":(?:G|3p)") and (not prevword1(s, m.start()) or look(s[:m.start()], r"(?i)\b(?:parce que?|quoi ?que?|pour ?quoi|puisque?|quand|com(?:ment|bien)|car|tandis que?) +$"))
def s5663s_1 (s, m):
    return m.group(1)[:-1]+"t"
def c5666s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V", ":(?:3s|P|G)") and morphex(dDA, prevword1(s, m.start()), ":C", ":(?:Y|P|Q|[123][sp]|R)", True) and not( m.group(1).endswith("ien") and look(s[:m.start()], "> +$") and morph(dDA, (m.start(2), m.group(2)), ":Y", False) )
def s5666s_1 (s, m):
    return suggVerb(m.group(2), ":3s")
def c5684s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V", ":(?:3s|P|G|Q)") and morphex(dDA, prevword1(s, m.start()), ":C", ":(?:Y|P|Q|[123][sp]|R)", True)
def s5684s_1 (s, m):
    return suggVerb(m.group(2), ":3s")
def c5688s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V", ":(?:3s|P|G)") and morphex(dDA, prevword1(s, m.start()), ":C", ":(?:Y|P|Q|[123][sp]|R)", True)
def s5688s_1 (s, m):
    return suggVerb(m.group(2), ":3s")
def c5696s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":Y", False) and morph(dDA, (m.start(2), m.group(2)), ":V.[a-z_!?]+(?!.*:(?:3s|P|Q|Y|3p!))")
def s5696s_1 (s, m):
    return suggVerb(m.group(2), ":3s")
def c5704s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, prevword1(s, m.start()), ":C", ":(?:Y|P)", True) and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:[si]", False) and morphex(dDA, (m.start(3), m.group(3)), ":V", ":(?:3s|P|Q|Y|3p!|G)") and not (look(s[:m.start()], r"(?i)\b(?:et|ou) +$") and morph(dDA, (m.start(3), m.group(3)), ":[1-3]p", False)) and not look(s[:m.start()], r"(?i)\bni .* ni\b") and not checkAgreement(m.group(2), m.group(3))
def s5704s_1 (s, m):
    return suggVerb(m.group(3), ":3s")
def c5708s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, prevword1(s, m.start()), ":C", ":(?:Y|P)", True) and morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:[si]", False) and morphex(dDA, (m.start(3), m.group(3)), ":V", ":(?:3s|1p|P|Q|Y|3p!|G)") and not (look(s[:m.start()], r"(?i)\b(?:et|ou) +$") and morph(dDA, (m.start(3), m.group(3)), ":[123]p", False)) and not look(s[:m.start()], r"(?i)\bni .* ni\b")
def s5708s_1 (s, m):
    return suggVerb(m.group(3), ":3s")
def c5731s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, prevword1(s, m.start()), ":C", ":(?:Y|P)", True) and isAmbiguousAndWrong(m.group(2), m.group(3), ":s", ":3s") and not (look(s[:m.start()], r"(?i)\b(?:et|ou) +$") and morph(dDA, (m.start(3), m.group(3)), ":(?:[123]p|p)", False)) and not look(s[:m.start()], r"(?i)\bni .* ni\b")
def s5731s_1 (s, m):
    return suggVerb(m.group(3), ":3s", suggSing)
def c5736s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, prevword1(s, m.start()), ":C", ":(?:Y|P)", True) and isVeryAmbiguousAndWrong(m.group(2), m.group(3), ":s", ":3s", not prevword1(s, m.start())) and not (look(s[:m.start()], r"(?i)\b(?:et|ou) +$") and morph(dDA, (m.start(3), m.group(3)), ":(?:[123]p|p)", False)) and not look(s[:m.start()], r"(?i)\bni .* ni\b")
def s5736s_1 (s, m):
    return suggVerb(m.group(3), ":3s", suggSing)
def c5742s_1 (s, sx, m, dDA, sCountry):
    return ( morph(dDA, (m.start(0), m.group(0)), ":1s") or ( look(s[:m.start()], "> +$") and morph(dDA, (m.start(0), m.group(0)), ":1s", False) ) ) and not (m.group(0)[0:1].isupper() and look(sx[:m.start()], r"\w")) and not look(sx[:m.start()], r"(?i)\b(?:j(?:e |[’'])|moi(?:,? qui| seul) )")
def s5742s_1 (s, m):
    return suggVerb(m.group(0), ":3s")
def c5746s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(0), m.group(0)), ":2s", ":(?:E|G|W|M|J|[13][sp]|2p)") and not m.group(0)[0:1].isupper() and not look(s[:m.start()], "^ *$") and ( not morph(dDA, (m.start(0), m.group(0)), ":[NAQ]", False) or look(s[:m.start()], "> +$") ) and not look(sx[:m.start()], r"(?i)\bt(?:u |[’']|oi,? qui |oi seul )")
def s5746s_1 (s, m):
    return suggVerb(m.group(0), ":3s")
def c5751s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(0), m.group(0)), ":2s", ":(?:G|W|M|J|[13][sp]|2p)") and not (m.group(0)[0:1].isupper() and look(sx[:m.start()], r"\w")) and ( not morph(dDA, (m.start(0), m.group(0)), ":[NAQ]", False) or look(s[:m.start()], "> +$") ) and not look(sx[:m.start()], r"(?i)\bt(?:u |[’']|oi,? qui |oi seul )")
def s5751s_1 (s, m):
    return suggVerb(m.group(0), ":3s")
def c5756s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(0), m.group(0)), ":[12]s", ":(?:E|G|W|M|J|3[sp]|2p|1p)") and not (m.group(0)[0:1].isupper() and look(sx[:m.start()], r"\w")) and ( not morph(dDA, (m.start(0), m.group(0)), ":[NAQ]", False) or look(s[:m.start()], "> +$") or ( re.search("(?i)^étais$", m.group(0)) and not morph(dDA, prevword1(s, m.start()), ":[DA].*:p", False, True) ) ) and not look(sx[:m.start()], r"(?i)\b(?:j(?:e |[’'])|moi(?:,? qui| seul) |t(?:u |[’']|oi,? qui |oi seul ))")
def s5756s_1 (s, m):
    return suggVerb(m.group(0), ":3s")
def c5761s_1 (s, sx, m, dDA, sCountry):
    return not (m.group(0)[0:1].isupper() and look(sx[:m.start()], r"\w")) and not look(sx[:m.start()], r"(?i)\b(?:j(?:e |[’'])|moi(?:,? qui| seul) |t(?:u |[’']|oi,? qui |oi seul ))")
def s5761s_1 (s, m):
    return suggVerb(m.group(0), ":3s")
def c5764s_1 (s, sx, m, dDA, sCountry):
    return not (m.group(0)[0:1].isupper() and look(sx[:m.start()], r"\w")) and not look(sx[:m.start()], r"(?i)\b(?:j(?:e |[’'])|moi(?:,? qui| seul) |t(?:u |[’']|oi,? qui |oi seul ))")
def s5764s_1 (s, m):
    return suggVerb(m.group(0), ":3s")
def c5772s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V", ":(?:1p|3[sp])") and not look(s[m.end():], "^ +(?:je|tu|ils?|elles?|on|[vn]ous)")
def s5772s_1 (s, m):
    return suggVerb(m.group(1), ":1p")
def c5775s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V", ":1p") and not look(s[m.end():], "^ +(?:je|tu|ils?|elles?|on|[vn]ous)")
def s5775s_1 (s, m):
    return suggVerb(m.group(1), ":1p")
def c5778s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V", ":1p") and not look(s[m.end():], "^ +(?:ils|elles)")
def s5778s_1 (s, m):
    return suggVerb(m.group(1), ":1p")
def c5787s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V", ":(?:2p|3[sp])") and not look(s[m.end():], "^ +(?:je|ils?|elles?|on|[vn]ous)")
def s5787s_1 (s, m):
    return suggVerb(m.group(1), ":2p")
def c5790s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V", ":2p") and not look(s[m.end():], "^ +(?:je|ils?|elles?|on|[vn]ous)")
def s5790s_1 (s, m):
    return suggVerb(m.group(1), ":2p")
def c5799s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(0), m.group(0)), ":V.*:1p", ":[EGMNAJ]") and not (m.group(0)[0:1].isupper() and look(s[:m.start()], r"\w")) and not look(s[:m.start()], r"\b(?:[nN]ous(?:-mêmes?|)|[eE]t moi),? ")
def s5799s_1 (s, m):
    return suggVerb(m.group(0), ":3p")
def c5803s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(0), m.group(0)), ":V.*:2p", ":[EGMNAJ]") and not (m.group(0)[0:1].isupper() and look(s[:m.start()], r"\w")) and not look(s[:m.start()], r"\b(?:[vV]ous(?:-mêmes?|)|[eE]t toi|[tT]oi et),? ")
def c5812s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V", ":(?:3p|P|Q|G)") and not (morph(dDA, (m.start(2), m.group(2)), ":[PQ]", False) and morph(dDA, prevword1(s, m.start()), ":V0.*:3p", False, False))
def s5812s_1 (s, m):
    return suggVerb(m.group(2), ":3p")
def c5815s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V", ":(?:3p|P|Q|G)")
def s5815s_1 (s, m):
    return suggVerb(m.group(2), ":3p")
def c5819s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V", ":(?:3p|P|Q|G)")
def s5819s_1 (s, m):
    return suggVerb(m.group(2), ":3p")
def c5823s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V", ":(?:3p|P|Q|G)") and not morph(dDA, prevword1(s, m.start()), ":[VR]", False, False)
def s5823s_1 (s, m):
    return suggVerb(m.group(2), ":3p")
def c5827s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V", ":(?:3p|P|Q|G)") and not morph(dDA, prevword1(s, m.start()), ":R", False, False) and not (morph(dDA, (m.start(1), m.group(1)), ":[PQ]", False) and morph(dDA, prevword1(s, m.start()), ":V0.*:3p", False, False))
def s5827s_1 (s, m):
    return suggVerb(m.group(1), ":3p")
def c5830s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V", ":(?:3p|P|Q|G)") and not morph(dDA, prevword1(s, m.start()), ":R", False, False)
def s5830s_1 (s, m):
    return suggVerb(m.group(1), ":3p")
def c5845s_1 (s, sx, m, dDA, sCountry):
    return not look(s[:m.start()], r"(?i)\b(?:à|avec|sur|chez|par|dans|parmi|contre|ni|de|pour|sous) +$")
def c5852s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V", ":(?:3p|P|Q|mg)") and not morph(dDA, prevword1(s, m.start()), ":[VR]|>de ", False, False)
def s5852s_1 (s, m):
    return suggVerb(m.group(2), ":3p")
def c5856s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V", ":(?:3p|P|Q|G)") and not morph(dDA, prevword1(s, m.start()), ":[VR]", False, False)
def s5856s_1 (s, m):
    return suggVerb(m.group(2), ":3p")
def c5866s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V", ":(?:G|N|A|3p|P|Q)") and not morph(dDA, prevword1(s, m.start()), ":[VR]", False, False)
def s5866s_1 (s, m):
    return suggVerb(m.group(2), ":3p")
def c5873s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:[pi]", False) and morphex(dDA, (m.start(3), m.group(3)), ":V", ":(?:[13]p|P|Q|Y|G|A.*:e:[pi])") and morphex(dDA, prevword1(s, m.start()), ":C", ":[YP]", True) and not checkAgreement(m.group(2), m.group(3))
def s5873s_1 (s, m):
    return suggVerb(m.group(3), ":3p")
def c5876s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(2), m.group(2)), ":[NAQ].*:[pi]", False) and morphex(dDA, (m.start(3), m.group(3)), ":V", ":(?:[13]p|P|Y|G)") and morphex(dDA, prevword1(s, m.start()), ":C", ":[YP]", True)
def s5876s_1 (s, m):
    return suggVerb(m.group(3), ":3p")
def c5896s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:[pi]", False) and morphex(dDA, (m.start(2), m.group(2)), ":V", ":(?:[13]p|P|G|Q.*:p)") and morph(dDA, nextword1(s, m.end()), ":(?:R|D.*:p)|>au ", False, True)
def s5896s_1 (s, m):
    return suggVerb(m.group(2), ":3p")
def c5899s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":[NAQ].*:[pi]", False) and morphex(dDA, (m.start(2), m.group(2)), ":V", ":(?:[13]p|P|G)")
def s5899s_1 (s, m):
    return suggVerb(m.group(2), ":3p")
def c5905s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, prevword1(s, m.start()), ":C", ":[YP]", True) and isAmbiguousAndWrong(m.group(2), m.group(3), ":p", ":3p")
def s5905s_1 (s, m):
    return suggVerb(m.group(3), ":3p", suggPlur)
def c5909s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, prevword1(s, m.start()), ":C", ":[YP]", True) and isVeryAmbiguousAndWrong(m.group(1), m.group(2), ":p", ":3p", not prevword1(s, m.start()))
def s5909s_1 (s, m):
    return suggVerb(m.group(2), ":3p", suggPlur)
def c5913s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, prevword1(s, m.start()), ":C", ":[YP]", True) and isVeryAmbiguousAndWrong(m.group(1), m.group(2), ":m:p", ":3p", not prevword1(s, m.start()))
def s5913s_1 (s, m):
    return suggVerb(m.group(2), ":3p", suggMasPlur)
def c5917s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, prevword1(s, m.start()), ":C", ":[YP]", True) and isVeryAmbiguousAndWrong(m.group(1), m.group(2), ":f:p", ":3p", not prevword1(s, m.start()))
def s5917s_1 (s, m):
    return suggVerb(m.group(2), ":3p", suggFemPlur)
def c5950s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V0e", ":3s")
def s5950s_1 (s, m):
    return suggVerb(m.group(1), ":3s")
def c5954s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V0e.*:3s", ":3p")
def s5954s_1 (s, m):
    return m.group(1)[:-1]
def c5960s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V0e", ":3p")
def s5960s_1 (s, m):
    return suggVerb(m.group(1), ":3p")
def c5964s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":V0e.*:3p", ":3s")
def c5975s_1 (s, sx, m, dDA, sCountry):
    return not look(s[:m.start()], r"\b(?:et |ou |[dD][eu] |ni |[dD]e l’) *$") and morph(dDA, (m.start(1), m.group(1)), ":M", False) and morphex(dDA, (m.start(2), m.group(2)), ":[123][sp]", ":(?:G|3s|3p!|P|M|[AQ].*:[si])") and not morph(dDA, prevword1(s, m.start()), ":[VRD]", False, False) and not look(s[:m.start()], r"([A-ZÉÈ][\w-]+), +([A-ZÉÈ][\w-]+), +$")
def s5975s_1 (s, m):
    return suggVerb(m.group(2), ":3s")
def c5982s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":M", False) and morph(dDA, (m.start(2), m.group(2)), ":M", False) and morphex(dDA, (m.start(3), m.group(3)), ":[123][sp]", ":(?:G|3p|P|Q.*:[pi])") and not morph(dDA, prevword1(s, m.start()), ":R", False, False)
def s5982s_1 (s, m):
    return suggVerb(m.group(3), ":3p")
def c6000s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":(?:[12]s|3p)", ":(?:3s|G|W|3p!)") and not look(s[m.end():], "^ +et (?:l(?:es? |a |’|eurs? )|[mts](?:a|on|es) |ce(?:tte|ts|) |[nv]o(?:s|tre) |du )")
def s6000s_1 (s, m):
    return suggVerb(m.group(1), ":3s")
def c6005s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":[123]s", ":(?:3p|G|W)")
def s6005s_1 (s, m):
    return suggVerb(m.group(1), ":3p")
def c6010s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":[12][sp]", ":(?:G|W|3[sp]|Y|P|Q)")
def c6015s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":[12][sp]", ":(?:G|W|3[sp])")
def c6029s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V.*:1s", ":[GNW]") and not look(s[:m.start()], r"(?i)\bje +>? *$")
def s6029s_1 (s, m):
    return m.group(1)[:-1]+"é-je"
def c6032s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":V.*:1s", ":[GNW]") and not look(s[:m.start()], r"(?i)\b(?:je|tu) +>? *$")
def c6035s_1 (s, sx, m, dDA, sCountry):
    return not look(s[m.end():], "^ +(?:en|y|ne|>)") and morphex(dDA, (m.start(1), m.group(1)), ":V.*:2s", ":[GNW]") and not look(s[:m.start()], r"(?i)\b(?:je|tu) +>? *$")
def c6038s_1 (s, sx, m, dDA, sCountry):
    return not look(s[m.end():], "^ +(?:en|y|ne|>)") and morphex(dDA, (m.start(1), m.group(1)), ":V.*:3s", ":[GNW]") and not look(s[:m.start()], r"(?i)\b(?:ce|il|elle|on) +>? *$")
def s6038s_1 (s, m):
    return m.group(0).replace(" ", "-")
def c6041s_1 (s, sx, m, dDA, sCountry):
    return not look(s[m.end():], "^ +(?:en|y|ne|aussi|>)") and morphex(dDA, (m.start(1), m.group(1)), ":V.*:3s", ":[GNW]") and not look(s[:m.start()], r"(?i)\b(?:ce|il|elle|on) +>? *$")
def c6044s_1 (s, sx, m, dDA, sCountry):
    return not look(s[m.end():], "^ +(?:en|y|ne|aussi|>)") and morphex(dDA, (m.start(1), m.group(1)), ":V.*:1p", ":[GNW]") and not morph(dDA, prevword1(s, m.start()), ":Os", False, False) and not morph(dDA, nextword1(s, m.end()), ":Y", False, False)
def c6048s_1 (s, sx, m, dDA, sCountry):
    return not look(s[m.end():], "^ +(?:en|y|ne|aussi|>)") and not m.group(1).endswith("euillez") and morphex(dDA, (m.start(1), m.group(1)), ":V.*:2pl", ":[GNW]") and not morph(dDA, prevword1(s, m.start()), ":Os", False, False) and not morph(dDA, nextword1(s, m.end()), ":Y", False, False)
def c6052s_1 (s, sx, m, dDA, sCountry):
    return not look(s[m.end():], "^ +(?:en|y|ne|aussi|>)") and morphex(dDA, (m.start(1), m.group(1)), ":V.*:3p", ":[GNW]") and not look(s[:m.start()], r"(?i)\b(?:ce|ils|elles) +>? *$")
def s6052s_1 (s, m):
    return m.group(0).replace(" ", "-")
def c6057s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, (m.start(1), m.group(1)), ":1[sśŝ]", False) and _oDict.isValid(m.group(1)) and not re.search("(?i)^vite$", m.group(1))
def s6057s_1 (s, m):
    return suggVerb(m.group(1), ":1ś")
def c6060s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, (m.start(1), m.group(1)), ":[ISK].*:2s", False) and _oDict.isValid(m.group(1)) and not re.search("(?i)^vite$", m.group(1))
def s6060s_1 (s, m):
    return suggVerb(m.group(1), ":2s")
def c6063s_1 (s, sx, m, dDA, sCountry):
    return m.group(1) != "t" and not morph(dDA, (m.start(1), m.group(1)), ":3s", False) and (not m.group(1).endswith("oilà") or m.group(2) != "il") and _oDict.isValid(m.group(1)) and not re.search("(?i)^vite$", m.group(1))
def s6063s_1 (s, m):
    return suggVerb(m.group(1), ":3s")
def c6066s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":3p", ":3s") and _oDict.isValid(m.group(1))
def c6069s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, (m.start(1), m.group(1)), ":(?:1p|E:2[sp])", False) and _oDict.isValid(m.group(1)) and not re.search("(?i)^(?:vite|chez)$", m.group(1))
def s6069s_1 (s, m):
    return suggVerb(m.group(1), ":1p")
def c6072s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, (m.start(1), m.group(1)), ":2p", False) and _oDict.isValid(m.group(1)) and not re.search("(?i)^(?:tes|vite)$", m.group(1)) and not _oDict.isValid(m.group(0))
def s6072s_1 (s, m):
    return suggVerb(m.group(1), ":2p")
def c6075s_1 (s, sx, m, dDA, sCountry):
    return m.group(1) != "t" and not morph(dDA, (m.start(1), m.group(1)), ":3p", False) and _oDict.isValid(m.group(1))
def s6075s_1 (s, m):
    return suggVerb(m.group(1), ":3p")
def c6079s_1 (s, sx, m, dDA, sCountry):
    return not morph(dDA, (m.start(1), m.group(1)), ":V", False) and not re.search("(?i)^vite$", m.group(1)) and _oDict.isValid(m.group(1)) and not ( m.group(0).endswith("il") and m.group(1).endswith("oilà") ) and not ( m.group(1) == "t" and m.group(0).endswith(("il", "elle", "on", "ils", "elles")) )
def c6099s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":(?:Os|M)", False) and morphex(dDA, (m.start(2), m.group(2)), ":[SK]", ":(?:G|V0|I)") and not prevword1(s, m.start())
def c6102s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":[SK]", ":(?:G|V0|I)") and not prevword1(s, m.start())
def c6106s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":(?:Os|M)", False) and morphex(dDA, (m.start(2), m.group(2)), ":S", ":[IG]")
def s6106s_1 (s, m):
    return suggVerbMode(m.group(2), ":I", m.group(1))
def c6106s_2 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":(?:Os|M)", False) and morph(dDA, (m.start(2), m.group(2)), ":K", False)
def s6106s_2 (s, m):
    return suggVerbMode(m.group(2), ":If", m.group(1))
def c6113s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ">(?:afin|pour|quoi|permettre|falloir|vouloir|ordonner|exiger|désirer|douter|suffire) ", False) and morph(dDA, (m.start(2), m.group(2)), ":(?:Os|M)", False) and not morph(dDA, (m.start(3), m.group(3)), ":[GYS]", False) and not (morph(dDA, (m.start(1), m.group(1)), ">douter ", False) and morph(dDA, (m.start(3), m.group(3)), ":If", False))
def s6113s_1 (s, m):
    return suggVerbMode(m.group(3), ":S", m.group(2))
def c6123s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":(?:Os|M)", False) and not morph(dDA, (m.start(2), m.group(2)), ":[GYS]", False)
def s6123s_1 (s, m):
    return suggVerbMode(m.group(2), ":S", m.group(1))
def c6128s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(2), m.group(2)), ":S", ":[GIK]") and not re.search("^e(?:usse|û[mt]es|ût)", m.group(2))
def s6128s_1 (s, m):
    return suggVerbMode(m.group(2), ":I", m.group(1))
def c6131s_1 (s, sx, m, dDA, sCountry):
    return morphex(dDA, (m.start(1), m.group(1)), ":S", ":[GIK]") and m.group(1) != "eusse"
def s6131s_1 (s, m):
    return suggVerbMode(m.group(1), ":I", "je")
def c6136s_1 (s, sx, m, dDA, sCountry):
    return morph(dDA, (m.start(1), m.group(1)), ":(?:Os|M)", False) and morph(dDA, (m.start(2), m.group(2)), ":V.*:S")
def s6136s_1 (s, m):
    return suggVerbMode(m.group(2), ":I", m.group(1))

