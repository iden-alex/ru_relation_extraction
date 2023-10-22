#!/usr/bin/env python

# Script to convert a column-based BIO-formatted entity-tagged file
# into standoff with reference to the original text.



import re
import sys
import os


class taggedEntity:
    def __init__(self, startOff, endOff, eType, idNum, fullText):
        self.startOff = startOff
        self.endOff = endOff
        self.eType = eType
        self.idNum = idNum
        self.fullText = fullText

        self.eText = fullText[startOff:endOff]

    def __str__(self):
        return "T%d\t%s %d %d\t%s" % (self.idNum, self.eType, self.startOff,
                                      self.endOff, self.eText)

    def check(self):
        # sanity checks: the string should not contain newlines and
        # should be minimal wrt surrounding whitespace
        assert "\n" not in self.eText, \
            "ERROR: newline in entity: '%s'" % self.eText
        assert self.eText == self.eText.strip(), \
            "ERROR: entity contains extra whitespace: '%s'" % self.eText


def BIO_to_standoff(BIOtext, reftext, tokenidx=2, tagidx=-1):
    BIOlines = BIOtext.split('\n')
    return BIO_lines_to_standoff(BIOlines, reftext, tokenidx, tagidx)


next_free_id_idx = 1


def BIO_lines_to_standoff(BIOlines, reftext, tokenidx=2, tagidx=-1):
    global next_free_id_idx

    taggedTokens = []

    ri, bi = 0, 0
    while(ri < len(reftext)):
        if bi >= len(BIOlines):
            print("Warning: received BIO didn't cover given text", file=sys.stderr)
            break

        BIOline = BIOlines[bi]

        if re.match(r'^\s*$', BIOline):
            # the BIO has an empty line (sentence split); skip
            bi += 1
        else:
            # assume tagged token in BIO. Parse and verify
            fields = BIOline.split('\t')

            try:
                tokentext = fields[tokenidx]
            except BaseException:
                print("Error: failed to get token text " \
                    "(field %d) on line: %s" % (tokenidx, BIOline), file=sys.stderr)
                raise

            try:
                tag = fields[tagidx]
            except BaseException:
                print("Error: failed to get token text " \
                    "(field %d) on line: %s" % (tagidx, BIOline), file=sys.stderr)
                raise

            m = re.match(r'^([BIO])((?:-[A-Za-z0-9_-]+)?)$', tag)
            assert m, "ERROR: failed to parse tag '%s'" % tag
            ttag, ttype = m.groups()

            # strip off starting "-" from tagged type
            if len(ttype) > 0 and ttype[0] == "-":
                ttype = ttype[1:]

            # sanity check
            assert ((ttype == "" and ttag == "O") or
                    (ttype != "" and ttag in ("B", "I"))), \
                "Error: tag/type mismatch %s" % tag

            # go to the next token on reference; skip whitespace
            while ri < len(reftext) and reftext[ri].isspace():
                ri += 1

            # verify that the text matches the original
            assert reftext[ri:ri + len(tokentext)] == tokentext, \
                "ERROR: text mismatch: reference '%s' tagged '%s'" % \
                (reftext[ri:ri + len(tokentext)].encode("UTF-8"),
                 tokentext.encode("UTF-8"))

            # store tagged token as (begin, end, tag, tagtype) tuple.
            taggedTokens.append((ri, ri + len(tokentext), ttag, ttype))

            # skip the processed token
            ri += len(tokentext)
            bi += 1

            # ... and skip whitespace on reference
            while ri < len(reftext) and reftext[ri].isspace():
                ri += 1

    # if the remaining part either the reference or the tagged
    # contains nonspace characters, something's wrong
    if (len([c for c in reftext[ri:] if not c.isspace()]) != 0 or
            len([c for c in BIOlines[bi:] if not re.match(r'^\s*$', c)]) != 0):
        assert False, "ERROR: failed alignment: '%s' remains in reference, " \
            "'%s' in tagged" % (reftext[ri:], BIOlines[bi:])

    standoff_entities = []

    # cleanup for tagger errors where an entity begins with a
    # "I" tag instead of a "B" tag
    revisedTagged = []
    prevTag = None
    for startoff, endoff, ttag, ttype in taggedTokens:
        if prevTag == "O" and ttag == "I":
            print("Note: rewriting \"I\" -> \"B\" after \"O\"", file=sys.stderr)
            ttag = "B"
        revisedTagged.append((startoff, endoff, ttag, ttype))
        prevTag = ttag
    taggedTokens = revisedTagged

    # cleanup for tagger errors where an entity switches type
    # without a "B" tag at the boundary
    revisedTagged = []
    prevTag, prevType = None, None
    for startoff, endoff, ttag, ttype in taggedTokens:
        if prevTag in ("B", "I") and ttag == "I" and prevType != ttype:
            print("Note: rewriting \"I\" -> \"B\" at type switch", file=sys.stderr)
            ttag = "B"
        revisedTagged.append((startoff, endoff, ttag, ttype))
        prevTag, prevType = ttag, ttype
    taggedTokens = revisedTagged

    prevTag, prevEnd = "O", 0
    currType, currStart = None, None
    for startoff, endoff, ttag, ttype in taggedTokens:

        if prevTag != "O" and ttag != "I":
            # previous entity does not continue into this tag; output
            assert currType is not None and currStart is not None, \
                "ERROR in %s" % fn

            standoff_entities.append(taggedEntity(currStart, prevEnd, currType,
                                                  next_free_id_idx, reftext))

            next_free_id_idx += 1

            # reset current entity
            currType, currStart = None, None

        elif prevTag != "O":
            # previous entity continues ; just check sanity
            assert ttag == "I", "ERROR in %s" % fn
            assert currType == ttype, "ERROR: entity of type '%s' continues " \
                "as type '%s'" % (currType, ttype)

        if ttag == "B":
            # new entity starts
            currType, currStart = ttype, startoff

        prevTag, prevEnd = ttag, endoff

    # if there's an open entity after all tokens have been processed,
    # we need to output it separately
    if prevTag != "O":
        standoff_entities.append(taggedEntity(currStart, prevEnd, currType,
                                              next_free_id_idx, reftext))
        next_free_id_idx += 1

    for e in standoff_entities:
        e.check()

    return standoff_entities


RANGE_RE = re.compile(r'^(-?\d+)-(-?\d+)$')


def parse_indices(idxstr):
    # parse strings of forms like "4,5" and "6,8-11", return list of
    # indices.
    indices = []
    for i in idxstr.split(','):
        if not RANGE_RE.match(i):
            indices.append(int(i))
        else:
            start, end = RANGE_RE.match(i).groups()
            for j in range(int(start), int(end)):
                indices.append(j)
    return indices


def main(b):

    tokenIdx =0
    bioIdx = 1

    textfile_path = 'rured/annotation_files/'
    biofile_path = 'my_rured/'
    f_names = [f for f in os.listdir(textfile_path) if f.endswith(".txt")]
    global next_free_id_idx
    for f_name in f_names:
        next_free_id_idx  = 1
        with open(textfile_path + f_name, 'r', encoding='utf-8') as f:
            text = f.read()
            text = text[:text.rfind('\n\n')]
        with open(biofile_path + f_name, 'r', encoding='utf-8') as f:
            bio = f.read()
        so = []
        so.extend(BIO_to_standoff(bio, text, tokenIdx, bioIdx))
        with open(biofile_path + f_name[:-3]+'ann', 'w', encoding='utf-8') as f:
            for s in so:
                print(s ,file=f)

    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))
