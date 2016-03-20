### python print.py [as/a/s] [varname]

import sqlitedict
import sys
import numpy


def ndprint(a, format_string ='{0:9.2e}'):
    print [format_string.format(v,i) for i,v in enumerate(a)]

if sys.argv[1] == 'as':
    filename = 'aerostruct'
elif sys.argv[1] == 'a':
    filename = 'weissinger'
elif sys.argv[1] == 's':
    filename = 'spatialbeam'
else:
    raise Exception('Please choose as, a, or s')
varname = sys.argv[2]

db = sqlitedict.SqliteDict(filename + '.db', 'openmdao')

counter = 0
for case_name, case_data in db.iteritems():
    if "metadata" in case_name or "derivs" in case_name:
        continue # don't plot these cases

    print '%5i' % counter,
#    print numpy.array_str(case_data['Unknowns'][varname], precision=3)
    ndprint(case_data['Unknowns'][varname])

    counter += 1
