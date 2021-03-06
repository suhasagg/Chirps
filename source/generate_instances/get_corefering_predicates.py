import codecs

from docopt import docopt
from fuzzywuzzy import fuzz
from spacy.en import English
from num2words import num2words
from collections import defaultdict
from nltk.corpus import wordnet as wn
from guess_language import guessLanguage

nlp = English()

MAX_PRED_FOR_ARG_PAIR = 5


def main():
    """
    Receives a file with propositions extracted from same event tweets,
    and aligns predicates / arguments based on string matching / WordNET synset matching of two
    items for the proposition.
    """
    args = docopt("""Receives a file with propositions extracted from same event tweets,
    and aligns predicates / arguments based on string matching / WordNET synset matching of two
    items for the proposition.

    Usage:
        get_corefering_predicates.py <tweets_file> <out_file>

        <tweets_file> = the file containing the propositions from tweets discussing
        the same event, each line in the format: confidence\tpredicate\targ1\targ2\ttweet
        <out_file> = the output file, that will contain the positive instances.
    """)

    tweets_file = args['<tweets_file>']
    out_file = args['<out_file>']

    # Load a list of pronouns
    with codecs.open('pronouns.txt', 'r', 'utf-8') as f_in:
        pronouns = set([line.strip() for line in f_in])

    # Load the propositions file
    with codecs.open(tweets_file, 'r', 'utf-8', errors='replace') as f_in:
        propositions = [tuple(line.lower().strip().split('\t')) for line in f_in]

        # Unite consecutive arguments, e.g. "US government"
        for i, prop in enumerate(propositions):
            if len(prop) >= 9:
                tweet_id, sent, sf_pred, lemmatized_pred, _, a0, _, a1, _, a2 = prop[:10]
                if '{a0} {a1}' in lemmatized_pred:
                    sf_pred = sf_pred.replace('{a0} {a1}', '{a0}').replace('{a2}', '{a1}')
                    lemmatized_pred = lemmatized_pred.replace('{a0} {a1}', '{a0}').replace('{a2}', '{a1}')
                    a0 = a0 + ' ' + a1
                    a1 = a2
                    propositions[i] = (tweet_id, sent, sf_pred, lemmatized_pred, 'a0', a0, 'a1', a1)
                elif '{a1} {a2}' in lemmatized_pred:
                    sf_pred = sf_pred.replace('{a1} {a2}', '{a1}')
                    lemmatized_pred = lemmatized_pred.replace('{a1} {a2}', '{a1}')
                    a1 = a1 + ' ' + a2
                    propositions[i] = (tweet_id, sent, sf_pred, lemmatized_pred, 'a0', a0, 'a1', a1)

        # 0 - tweet_id, 1 - sentence, 2 - predicate, 3 - lemmatized predicate, 4 - "A0", 5 - A0, 6 - "A1", 7 - A1
        propositions = [(item[0], item[1], item[2][:item[2].index('{a1}') + 4].strip(),
                         item[3][:item[3].index('{a1}') + 4].strip(), item[5], item[7])
                        for item in propositions if len(item) >= 8 and '{a1}' in item[2]]

        # Remove non English sentences, those with short arguments and trivial / too general predicates
        propositions = [(tweet_id, sent, surface_pred, pred, a0, a1) for (tweet_id, sent, surface_pred, pred, a0, a1)
                        in propositions if guessLanguage(sent) == 'en' and len(a0) >= 2 and len(a1) >= 2
                        and pred not in ['{a0} {a1}', '{a1} {a0}', '{a0} be {a1}', '{a0} be {a1}']]

    # Find predicates that match by argument
    predicate_alignments = pair_aligned_propositions(propositions, pronouns)

    # Keep one tweet id pair and one (s,v,o) tuple for each instance
    filtered = {tuple(sorted([tweet_id1, tweet_id2])):
                    (tweet_id1, sent1, sf_pred1, pred1, sent1_a0, sent1_a1,
                     tweet_id2, sent2, sf_pred2, pred2, sent2_a0, sent2_a1)
                for (tweet_id1, sent1, sf_pred1, pred1, sent1_a0, sent1_a1,
                     tweet_id2, sent2, sf_pred2, pred2, sent2_a0, sent2_a1)
                in predicate_alignments}.values()

    filtered = {(tuple([pred1, sent1_a0, sent1_a1]), tuple([pred2, sent2_a0, sent2_a1])):
                    (tweet_id1, sent1, sf_pred1, pred1, sent1_a0, sent1_a1,
                     tweet_id2, sent2, sf_pred2, pred2, sent2_a0, sent2_a1)
                for (tweet_id1, sent1, sf_pred1, pred1, sent1_a0, sent1_a1,
                     tweet_id2, sent2, sf_pred2, pred2, sent2_a0, sent2_a1)
                in filtered}.values()

    print 'Extracted %d instances' % len(filtered)

    # Write the predicate alignments to the output file
    out_file = out_file.replace('.prop', '')

    if len(filtered) > 0:
        with codecs.open(out_file, 'w', 'utf-8') as f_out:
            for prop_pair in filtered:
                try:
                    date = tweets_file[tweets_file.index('/') + 1 if '/' in tweets_file else 0:]
                    print >> f_out, date + '\t' + '\t'.join(prop_pair)
                except:
                    print 'error'


def get_candidate_pairs(propositions, pronouns):

    global nlp

    # Remove propositions with argument pronouns
    propositions = [(tweet_id, sent, sf_pred, pred, a0, a1) for (tweet_id, sent, sf_pred, pred, a0, a1) in propositions
                    if len(pronouns.intersection(set([a0, a1]))) == 0 and len(sent) > 10]

    print 'Extracted %d propositions' % len(propositions)

    # Get candidates by lexical overlap in arguments
    candidates_by_args = defaultdict(set)

    [candidates_by_args[w].add(i) for i, (tweet_id, sent, sf_pred, pred, a0, a1) in enumerate(propositions)
     for w in a0.split() if not nlp.is_stop(w)]

    [candidates_by_args[w].add(i) for i, (tweet_id, sent, sf_pred, pred, a0, a1) in enumerate(propositions)
     for w in a1.split() if not nlp.is_stop(w)]

    # Get pairwise candidates from all lists
    candidates = set([propositions[i] + propositions[j] for lst in candidates_by_args.values()
                      for i in lst for j in lst if i != j])

    print 'Extracted %d candidates' % len(candidates)

    return candidates


def pair_aligned_propositions(propositions, pronouns):
    """
    Align predicates with the same arguments in different sentences
    :param propositions: the (sent, pred, arg1, arg2) tuples
    :return: a list of aligned_prop
    """
    predicate_alignments = []

    candidates = get_candidate_pairs(propositions, pronouns)

    for (tweet_id1, sent1, sf_pred1, pred1, s0_a0, s0_a1, tweet_id2, sent2, sf_pred2, pred2, s1_a0, s1_a1) in candidates:

        # Same tweet
        if fuzz.token_sort_ratio(sent1, sent2) >= 95:
            continue

        # Same predicates?
        if is_eq_preds(pred1, pred2):
            continue

        # Same arguments?
        is_eq_a0_a0, is_eq_a1_a1, is_eq_a0_a1, is_eq_a1_a0 = \
            is_eq_arg(s0_a0, s1_a0), is_eq_arg(s0_a1, s1_a1), is_eq_arg(s0_a0, s1_a1), is_eq_arg(s0_a1, s1_a0)

        # Are arguments aligned?
        is_aligned_a0_a0 = is_eq_a0_a0 or is_aligned_arg(s0_a0, s1_a0)
        is_aligned_a1_a1 = is_eq_a1_a1 or is_aligned_arg(s0_a1, s1_a1)
        is_aligned_a0_a1 = is_eq_a0_a1 or is_aligned_arg(s0_a0, s1_a1)
        is_aligned_a1_a0 = is_eq_a1_a0 or is_aligned_arg(s0_a1, s1_a0)

        # Are predicates aligned?
        is_aligned_pred = is_aligned_preds(pred1, pred2)

        # 1) the predicates are not equal, one argument-pair is aligned/equal, the other argument-pair is equal =>
        # predicates are aligned
        if (is_eq_a0_a0 and is_aligned_a1_a1) or (is_aligned_a0_a0 and is_eq_a1_a1):
            predicate_alignments.append((tweet_id1, sent1, sf_pred1, pred1, s0_a0, s0_a1,
                                         tweet_id2, sent2, sf_pred2, pred2, s1_a0, s1_a1))
            continue

        # 2) all three items are aligned
        if is_aligned_pred and is_aligned_a0_a0 and is_aligned_a1_a1:
            predicate_alignments.append((tweet_id1, sent1, sf_pred1, pred1, s0_a0, s0_a1,
                                         tweet_id2, sent2, sf_pred2, pred2, s1_a0, s1_a1))
            continue

        # Same as before, but with reversed arguments
        if (is_eq_a0_a1 and is_aligned_a1_a0) or (is_aligned_a0_a1 and is_eq_a1_a0):
            new_pred2 = pred2.replace('{a0}', 'ARG0').replace('{a1}', '{a0}').replace('ARG0', '{a1}')
            new_sf_pred2 = sf_pred2.replace('{a0}', 'ARG0').replace('{a1}', '{a0}').replace('ARG0', '{a1}')
            predicate_alignments.append((tweet_id1, sent1, sf_pred1, pred1, s0_a0, s0_a1,
                                         tweet_id2, sent2, new_sf_pred2, new_pred2, s1_a1, s1_a0))
            continue

        if is_aligned_pred and is_aligned_a0_a1 and is_aligned_a1_a0:
            new_pred2 = pred2.replace('{a0}', 'ARG0').replace('{a1}', '{a0}').replace('ARG0', '{a1}')
            new_sf_pred2 = sf_pred2.replace('{a0}', 'ARG0').replace('{a1}', '{a0}').replace('ARG0', '{a1}')
            predicate_alignments.append((tweet_id1, sent1, sf_pred1, pred1, s0_a0, s0_a1,
                                         tweet_id2, sent2, new_sf_pred2, new_pred2, s1_a1, s1_a0))
            continue

    return predicate_alignments


def is_eq_arg(x, y):
    """
    Return whether these two words are equal, with fuzzy string matching.
    :param x: the first argument
    :param y: the second argument
    :return: Whether they are equal
    """
    if fuzz.ratio(x, y) >= 90:
        return True

    # Convert numbers to words
    x_words = [num2words(int(w)).replace('-', ' ') if w.isdigit() else w for w in x.split()]
    y_words = [num2words(int(w)).replace('-', ' ') if w.isdigit() else w for w in y.split()]

    # Partial entailment with equivalence, e.g. 'two girls' -> 'two kids':
    return fuzz.ratio(' '.join(x_words), ' '.join(y_words)) >= 85


def is_eq_preds(p1, p2):
    """
    Return whether these two predicates are equal, with fuzzy string matching.
    :param x: the first predicate
    :param y: the second predicate
    :return: Whether they are equal
    """
    global nlp

    # Levenshtein distance mostly
    if fuzz.ratio(p1, p2) >= 90:
        return True

    # Same verb
    if p1.replace('{a0} ', '{a0} be ') == p2 or p1.replace('{a0} ', '{a0} have ') == p2 or \
                    p2.replace('{a0} ', '{a0} be ') == p1 or p2.replace('{a0} ', '{a0} have ') == p1:
        return True

    return False


def is_aligned_preds(x, y):
    """
    Return whether these two words are aligned: they occur in the same WordNet synset.
    :param x: the first argument
    :param y: the second argument
    :return: Whether they are aligned
    """
    global nlp

    x_synonyms = set([lemma.lower().replace('_', ' ') for synset in wn.synsets(x) for lemma in synset.lemma_names()])
    y_synonyms = set([lemma.lower().replace('_', ' ') for synset in wn.synsets(y) for lemma in synset.lemma_names()])

    return len([w for w in x_synonyms.intersection(y_synonyms) if not nlp.is_stop(w)]) > 0


def is_aligned_arg(x, y):
    """
    Return whether these two arguments are aligned: they occur in the same WordNet synset.
    :param x: the first argument
    :param y: the second argument
    :return: Whether they are aligned
    """
    global nlp

    # Allow partial matching
    if fuzz.partial_ratio(' ' + x + ' ', ' ' + y + ' ') == 100:
        return True

    x_words = [w for w in x.split() if not nlp.is_stop(w)]
    y_words = [w for w in y.split() if not nlp.is_stop(w)]

    if len(x_words) == 0 or len(y_words) == 0:
        return False

    x_synonyms = [set([lemma.lower().replace('_', ' ') for synset in wn.synsets(w) for lemma in synset.lemma_names()])
                  for w in x_words]
    y_synonyms = [set([lemma.lower().replace('_', ' ') for synset in wn.synsets(w) for lemma in synset.lemma_names()])
                  for w in y_words]

    # One word - check whether there is intersection between synsets
    if len(x_synonyms) == 1 and len(y_synonyms) == 1 and \
                    len([w for w in x_synonyms[0].intersection(y_synonyms[0]) if not nlp.is_stop(w)]) > 0:
        return True

    # More than one word - align words from x with words from y
    intersections = [len([w for w in s1.intersection(s2) if not nlp.is_stop(w)])
                     for s1 in x_synonyms for s2 in y_synonyms]

    if len([intersection_len for intersection_len in intersections if intersection_len > 0]) >= \
                    0.75 * max(len(x_synonyms), len(y_synonyms)):
        return True

    return False


if __name__ == '__main__':
    main()
