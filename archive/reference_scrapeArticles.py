# # scrapeArticles
# A notebook for scraping article data from the ProQuest Newspapers Archive via scrapy.

# ### Parameters, Dependencies, and Preprocessing

# +
event_type = 'terroristattack' #@param {type:"string"}
scrape_window = 50 #@param {type:"integer"}
homepath = 'C:/Users/me/Google Drive/newscycle' #@param {type:"string"}

# for math
import datetime
from datetime import timedelta
import numpy as np
import math
import time

# for collecting and storing data
import os
import json
import csv
import scrapy
import itertools
import re
from tqdm import tqdm
from dateutil import parser
from scrapy.crawler import CrawlerProcess
from scrapy.spiders import CrawlSpider, Rule
from scrapy.item import Item, Field
from scrapy.selector import Selector


# for troubleshooting
import logging
from scrapy.utils.response import open_in_browser

# download/organize already existing dataset so we can avoid redundant scraping
event_label = event_type
event_type = event_type.replace(' ', '').lower()
try:
    articles = []
    with open(os.path.join(homepath, event_type, 'data/articles.jsonl')) as f:
        for line in f:
            articles.append(json.loads(line))
    articles = sorted(articles, key = lambda element: (int(element['databaseindex']), int(element['searchindex'])))
    databaseindices = np.array([a['databaseindex'] for a in articles])
    articles = np.array(articles)
except FileNotFoundError:
    articles = None


# -

# ### Search Parameter Generators

# #### Generator Functions

# +
## super bowls
def superbowlSearchGenerator(line, header, d0=None, d1=None):
    # grab date
    if not d0:
        datestring = line[header.index('Date')]
        d0 = datetime.datetime.strptime(datestring, '%b %d %Y')
    if not d1:    
        d1 = d0 + timedelta(days=scrape_window)

    # query is just date and "superbowl"
    query = 'PD({}-{}) AND ("superbowl" OR "super bowl")'.format(d0.strftime('%Y%m%d'), d1.strftime('%Y%m%d'))
    return query, d0, d1

def sotuSearchGenerator(line, header, d0=None, d1=None):
    # grab date
    if not d0:
        datestring = line[header.index('date')]
        d0 = parser.parse(datestring)
    if not d1:    
        d1 = d0 + timedelta(days=scrape_window)

    # query is just date and "superbowl"
    query = 'PD({}-{}) AND ("state of the union")'.format(d0.strftime('%Y%m%d'), d1.strftime('%Y%m%d'))
    return query, d0, d1

def worldseriesSearchGenerator(line, header, d0=None, d1=None):
    # grab date
    if not d0:
        datestring = line[header.index('date')]
        d0 = parser.parse(datestring)
    if not d1:    
        d1 = d0 + timedelta(days=scrape_window)

    # query is just date and "superbowl"
    query = 'PD({}-{}) AND ("world series")'.format(d0.strftime('%Y%m%d'), d1.strftime('%Y%m%d'))
    return query, d0, d1

def oscarSearchGenerator(line, header, d0=None, d1=None):
    # grab date
    if not d0:
        datestring = line[header.index('date')]
        d0 = parser.parse(datestring)
    if not d1:    
        d1 = d0 + timedelta(days=scrape_window)

    # query is just date and "oscar"
    query = 'PD({}-{}) AND ("oscars" OR "academy awards")'.format(d0.strftime('%Y%m%d'), d1.strftime('%Y%m%d'))
    return query, d0, d1

## terrorist attacks
proximityparam = 200    # required proximacy of query terms to one another
x = 2                   # number of keywords/phrases to require in a search result
def terroristattackSearchGenerator(line, header, d0=None, d1=None):
    
    # location and date
    location = ('("' + line[header.index('city')] + '" OR "' + line[header.index('provstate')] + '")')
    
    if not d0:
        if line[header.index('iday')] != str(0):
            d0 = datetime.datetime(int(line[header.index('iyear')]),
                                   int(line[header.index('imonth')]),
                                   int(line[header.index('iday')]))
        else:
            d0 = datetime.datetime(int(line[header.index('iyear')]),
                                   int(line[header.index('imonth')]), 1) #woah this is very wrong
    if not d1:
        d1 = d0 + timedelta(days=scrape_window)

    # (City, State) AND ((shooting) or (bombing) or (bomb) or (violence) or (murder) or (terrorism))
    #query = ('FT(' + location + ') AND (FT(shooting) OR FT(bombing) OR ' +
    #         'FT(bomb) OR FT(violence) OR FT(murder) OR FT(terrorism)) ' +
    #         'AND PD(' + d0.strftime('%Y%m%d') + '-' + d1.strftime('%Y%m%d') + ')')
    query = 'PD({}-{}) AND {}'.format(
        d0.strftime('%Y%m%d'),  d1.strftime('%Y%m%d'),
        xof(x,[
                 attackkeywords(line[header.index('attacktype1')]),
                 targetkeywords(line[header.index('targtype1')],
                                line[header.index('targsubtype1_txt')],
                                line[header.index('corp1')],
                                line[header.index('target1')]),
                 perpkeywords(line[header.index('gname')]),
                 #weaponkeywords(line[header.index('suicide')],
                 #               line[header.index('attacktype1')],
                 #               line[header.index('weaptype1')],
                 #               line[header.index('weapsubtype1')]),
                 #misckeywords(line[header.index('attacktype1')],
                 #             line[header.index('ishostkid')],
                 #             line[header.index('ransom')],
                 #             line[header.index('suicide')]),
                 'terroris*'
             ], location))
    return query, d0, d1

searchParamGenerators = {'terroristattack': terroristattackSearchGenerator, 'superbowl': superbowlSearchGenerator, 'sotu': sotuSearchGenerator,
                        'worldseries': worldseriesSearchGenerator, 'oscar': oscarSearchGenerator} 


# -

# #### Helper Functions

# +
def xof(x, options):
    # filters blank options and wraps them in parentheses
    options = ['(' + each + ')' for each in options if len(each) > 0]
    
    # sets x to minimum of number of options and specified maximum limit
    x = min(len(options), x)
    
    # 
    result = [' NEAR/{} '.format(proximityparam).join(list(combination))
              for combination in itertools.combinations(options, x)]
    return '((' + ') OR ('.join(result) + '))'

def xof(x, options, location):
    # filters blank options and wraps them in parentheses
    options = ['(' + each + ')' for each in options if len(each) > 0]
    
    # sets x to minimum of number of options and specified maximum limit
    x = min(len(options), x)
    
    # builds set of possible ways to fulfill constraints
    result = []
    for xcombo in itertools.combinations(options, x):
        constraints = ['{1} NEAR/{0} {2}'.format(proximityparam, *list(nearcombo))
                       for nearcombo in itertools.combinations(list(xcombo) + [location], 2)]
        result.append(' AND '.join(constraints))
    
    return '((' + ') OR ('.join(result) + '))'
    
# define set of keywords such that the presence of one 
def attackkeywords(attacktype1):
    keywords = []
    
    # parse attacktype1 - the attack category
    if attacktype1 == '1':
        keywords.append('assassin*')
    elif attacktype1 == '2':
        keywords.append('assault*')
        keywords.append('armed')
        pass
    elif attacktype1 == '3':
        keywords.append('bomb*')
        keywords.append('explo*')
    elif attacktype1 == '4':
        keywords.append('hijack*')
    elif attacktype1 == '5':
        keywords.append('hostage')
        keywords.append('barricade*')
    elif attacktype1 == '6':
        keywords.append('hostage*')
        keywords.append('kidnap*')
    elif attacktype1 == '7':
        keywords.append('facility')
        keywords.append('infrastructure')
        keywords.append('sabotage')
    elif attacktype1 == '8':
        keywords.append('assault*')
        keywords.append('unarmed')
        
    if len(keywords) > 0:
        return '(' + ') OR ('.join(keywords) + ')'
    else:
        return ''
        
def targetkeywords(targtype1, targsubtype1_txt, corp1, target1):
    keywords = []
    
    if targtype1 == '1':
        keywords.append('business')
    elif targtype1 == '2' or targtype1 == '22':
        keywords.append('government')
        keywords.append('political')
    elif targtype1 == '3':
        keywords.append('police')
    elif targtype1 == '4':
        keywords.append('military')
    elif targtype1 == '5':
        keywords.append('abortion')
    elif targtype1 == '6':
        keywords.append('airport')
        keywords.append('aircraft')
    elif targtype1 == '7':
        keywords.append('government')
        keywords.append('embass*')
        keywords.append('consul*')
    elif targtype1 == '8':
        keywords.append('school')
        keywords.append('"educational institution"')
        keywords.append('university')
        keywords.append('teach*')
        keywords.append('professor')
    elif targtype1 == '9':
        keywords.append('supplies')
    elif targtype1 == '10':
        keywords.append('journalist')
        keywords.append('reporter')
        keywords.append('media')
    elif targtype1 == '11':
        keywords.append('maritime')
        keywords.append('fishing')
        keywords.append('"oil tanker"')
        keywords.append('ferr*')
        keywords.append('yacht')
    elif targtype1 == '12':
        keywords.append('NGO')
        keywords.append('"non-governmental organization"')
    elif targtype1 == '15':
        keywords.append('religious')
        keywords.append('church')
        keywords.append('mosque')
        keywords.append('synagogue')
        keywords.append('imam')
        keywords.append('priest')
        keywords.append('bishop')
    elif targtype1 == '16':
        keywords.append('telecom*')
        keywords.append('transmitter')
        keywords.append('tower')
    elif targtype1 == '18':
        keywords.append('tourist')
        keywords.append('"tour bus*"')
        keywords.append('tour')
    elif targtype1 == '19':
        keywords.append('"public transport*"')
    elif targtype1 == '21':
        keywords.append('utilit*')
        keywords.append('"power line"')
        keywords.append('pipeline')
        keywords.append('transformer')
        keywords.append('"high tension line"')
        keywords.append('substation')
        keywords.append('lamppost')
        keywords.append('"street light"')

    targsubtype1_txt.replace('/Other Personnel', '')
    targsubtype1_txt.replace('/Facility', '')
    targsubtype1_txt.replace('/Ethnicity Identified', '')
    targsubtype1_txt.replace('Religion Identified', 'Religious')
    if targsubtype1_txt == 'Labor Union Related':
        targsubtype1_txt = 'Labor Union/Union'
    if targsubtype1_txt == 'Affiliated Institution':
        targsubtype1_txt = ''
    if targsubtype1_txt == 'Named Citizen':
        targsubtype1_txt = ''
    if targsubtype1_txt == 'Other (including online news agencies)':
        targsubtype1_txt = ''
    if targsubtype1_txt == 'Other Personnel':
        targsubtype1_txt = ''
    if targsubtype1_txt == 'Clinics':
        targsubtype1_txt = 'Abortion Clinics'
    if targsubtype1_txt == 'Personnel':
        targsubtype1_txt = 'Abortion Personnel'
    if targsubtype1_txt.count('(') > 0 or targsubtype1_txt.count(')') > 0:
        regex = re.compile(".*?\((.*?)\)")
        result = re.findall(regex, targsubtype1_txt)
        targsubtype1_txt = targsubtype1_txt[:targsubtype1_txt.find('(' + result[0] + ')')-1]
    
    targsubtype1_txt = ['"' + each.strip().rstrip() + '"' for each in targsubtype1_txt.split('/')]
    keywords += targsubtype1_txt
    
    if len(corp1) > 0:
        keywords.append('"' + corp1 + '"')
    
    if len(target1) > 0:
        keywords.append('"' + target1 + '"')
    
    keywords = [k for k in keywords if len(k) > 1]
    if len(keywords) > 0:
        return '(' + ') OR ('.join(keywords) + ')'
    else:
        return ''
    
    
def perpkeywords(gname):
    if len(gname) > 2 and gname != 'Unknown':
        return '("' + gname + '")'
    else:
        return ''

def weaponkeywords(suicide, attacktype1, weaptype1, weaptype2):
    keywords = []
    
    if weaptype1 == '1':
        keywords.append('biological')
    elif weaptype1 == '2':
        keywords.append('chemical')
    elif weaptype1 == '3':
        keywords.append('radiological')
        keywords.append('radioactive')
        keywords.append('radiation')
    elif weaptype1 == '4':
        keywords.append('nuclear')
    elif weaptype1 == '5':
        keywords.append('firearm')
        keywords.append('gun')
    elif weaptype1 == '6' and attacktype1 != '3':
        keywords.append('bomb*')
        keywords.append('explo*')
    elif weaptype1 == '7':
        keywords.append('fake')
    elif weaptype1 == '8':
        keywords.append('incendiary')
        keywords.append('arson')
        keywords.append('combustible')
        keywords.append('flammable')
        keywords.append('inflammable')
        keywords.append('fire')
    elif weaptype1 == '9':
        keywords.append('melee')
    elif weaptype1 == '10':
        keywords.append('vehicle')
        keywords.append('car')
        keywords.append('bus')
        keywords.append('truck')
        keywords.append('van')
        keywords.append('automobile')
    elif weaptype1 == '11' and attacktype1 != '7':
        keywords.append('sabotage')
    
    if weaptype2 == '1':
        keywords.append('poison*')
    elif weaptype2 == '30':
        keywords.append('explo*')
    elif weaptype2 == '2':
        keywords.append('automatic')
        keywords.append('semi-automatic')
    elif weaptype2 == '3':
        keywords.append('handgun')
    elif weaptype2 == '4':
        keywords.append('rifle')
        keywords.append('shotgun')
    elif (weaptype2 == '5' or weaptype2 == '6') and weaptype1 != '5':
        keywords.append('firearm')
        keywords.append('gun')
    elif weaptype2 == '7':
        keywords.append('grenade')
    elif weaptype2 == '8':
        keywords.append('mine')
    elif weaptype2 == '9':
        for keyword in ['"parcel bomb"', '"mail bomb"', '"package bomb"', '"note bomb"', '"message bomb"',
                        '"gift bomb"', '"present bomb"','"delivery bomb"', '"surprise bomb"', '"postal bomb"',
                        '"post bomb"']:
            keywords.append(keyword)
    elif weaptype2 == '10':
        keywords.append('"pressure trigger"')
    elif weaptype2 == '11':
        for keyword in ['projectile', 'rocket', 'mortar', 'RPG', 'missile']:
            keywords.append(keyword)
    elif weaptype2 == '12':
        for keyword in ['"remote device"', 'trigger', 'detonate']:
            keywords.append(keyword)
    elif weaptype2 == '13' and suicide != '1':
        keywords.append('suicide')
    elif weaptype2 == '14':
        keywords.append('"time fuse"')
    elif weaptype2 == '15' and weaptype1 != '10':
        keywords.append('vehicle')
        keywords.append('car')
        keywords.append('bus')
        keywords.append('truck')
        keywords.append('van')
        keywords.append('automobile')
    elif (weaptype2 == '16' or weaptype2 == '17') and weaptype1 != '6' and attacktype1 != '3':
        keywords.append('bomb*')
        keywords.append('explo*')
    elif weaptype2 == '28':
        keywords.append('dynamite')
        keywords.append('tnt')
    elif weaptype2 == '29':
        keywords.append('"sticky bomb"')
    elif weaptype2 == '18' and weaptype1 != '8':
        keywords.append('incendiary')
        keywords.append('arson')
        keywords.append('combustible')
        keywords.append('flammable')
        keywords.append('inflammable')
        keywords.append('fire')
    elif weaptype2 == '19':
        keywords.append('molotov')
        keywords.append('"petrol bomb"')
    elif weaptype2 == '20':
        keywords.append('gasoline')
        keywords.append('alcohol')
    elif weaptype2 == '21':
        keywords.append('blunt')
    elif weaptype2 == '22':
        keywords.append('fist')
        keywords.append('punch*')
        keywords.append('beat*')
        keywords.append('kick*')
    elif weaptype2 == '23':
        keywords.append('knife')
        keywords.append('sword')
        keywords.append('stab')
    elif weaptype2 == '24':
        keywords.append('rope')
        keywords.append('strangl*')
    elif weaptype2 == '26':
        keywords.append('suffocat*')
    
    keywords = [k for k in keywords if len(k) > 1]
    if len(keywords) > 0:
        return '(' + ') OR ('.join(keywords) + ')'
    else:
        return ''

def misckeywords(attacktype1, ishostkid, ransom, suicide):
    keywords = []
    
    if suicide == '1':
        keywords.append('suicide')
    if ransom == '1':
        keywords.append('ransom')
    if ishostkid == '1' and attacktype1 != '5' and attacktype1 != '6':
        keywords.append('hostage*')
        keywords.append('kidnap*')
    
    keywords = [k for k in keywords if len(k) > 1]
    if len(keywords) > 0:
        return '(' + ') OR ('.join(keywords) + ')'
    else:
        return ''


# -

def parseDate(info, eventdate, maxdays):
    # remove the duplicate label
    original = info
    info = info.replace(' [Duplicate]', '')
    
    # remove content after a second-to-last comma if two exist
    try:
        info = ', '.join(info.split(', ')[-2:])
    except Exception:
        pass
    
    # remove everything before a first parenthesis if one exists
    try:
        info = info[info.rfind('(')+1:]
    except Exception:
        pass
    
    # between periods
    try:
        datetext = info.split('. ')[-2]
        parsed = parser.parse(datetext, fuzzy=True)
        assert 0 <= (parsed-eventdate).days < maxdays
        return parser.parse(datetext, fuzzy=True)
    except Exception:
        pass
    
    # before last bracket, after last colon
    try:
        datetext = info[info.rfind(']')+1:]
        datetext = datetext[:datetext.rfind(':')]
        datetext = datetext.replace(')', '')
        assert any([str(i) in datetext for i in range(10)])
        parsed = parser.parse(datetext, fuzzy=True)
        assert 0 <= (parsed-eventdate).days < maxdays
        return parsed
    except Exception:
        pass
    
    # remove everything before last bracket
    try:
        datetext = info[info.rfind(']')+1:]
        parsed = parser.parse(datetext, fuzzy=True)
        assert 0 <= (parsed-eventdate).days < maxdays
        return parsed
    except Exception:
        pass
    
    # remove everything after last colon
    try:
        datetext = info[:info.rfind(':')]
        parsed = parser.parse(datetext, fuzzy=True)
        assert 0 <= (parsed-eventdate).days < maxdays
        return parsed
    except Exception:
        pass
    
    # see if parser can solve by itself
    try:
        datetext = info
        parsed = parser.parse(datetext, fuzzy=True)
        assert 0 <= (parsed-eventdate).days < maxdays
        return parsed
    except Exception:
        pass
    
    # try again without content after first colon
    if ':' in original:
        return parseDate(original[:original.rfind(':')], eventdate, maxdays)


# ### Scraping Helper Classes

# +
# organizes the information we scrape about each article
class ArticleItem(scrapy.Item):
    
    # info defined by event data set
    databaseindex = scrapy.Field()
    
    # info defined by search process
    resultscount = scrapy.Field()
    query = scrapy.Field()
    originalquery = scrapy.Field()
    originalstart = scrapy.Field()
    originalend = scrapy.Field()
    querystart = scrapy.Field()
    queryend = scrapy.Field()
    parents = scrapy.Field()
    
    # info defined by article content
    searchindex = scrapy.Field()
    title = scrapy.Field()
    info = scrapy.Field()
    link  = scrapy.Field()
    
    # info derived from those above
    daysFrom = scrapy.Field()

# what happens to each generated article item,
# stores all scraped items into a single articles.jl file
class JsonWriterPipeline(object):

    # operations performed when spider starts
    def open_spider(self, spider):
        self.file = open(os.path.join(homepath, event_type, 'data/articles.jsonl'), 'a')

    # when the spider finishes
    def close_spider(self, spider):
        self.file.close()

    # when the spider yields an item
    def process_item(self, item, spider):
        line = json.dumps(dict(item)) + "\n"
        self.file.write(line)
        return item 


# -

# ### Spider Definition

# +
header = None
maxpossiblepages = 100

class articleSpider(scrapy.Spider):
    name = 'superbowl'
    custom_settings = {'HTTPERROR_ALLOWED_CODES': [500],
                      'ITEM_PIPELINES': {'__main__.JsonWriterPipeline': 1},
                      'LOG_LEVEL': 'WARNING'}
    
    def start_requests(self):
        global header
        totalsearches = 0
        
        # scan through database
        counter = 0
        f = open(os.path.join(homepath, event_type, 'data/{}s.csv'.format(event_type)), encoding='utf-8')
        event_csv = csv.reader(f)
        t = tqdm(total=1630)
        
        for line in event_csv:
            counter += 1
            t.update()
            
            if counter == 1:
                header = line
                continue
                
            # generate search content
            query, d0, d1 = searchParamGenerators[event_type](line, header)
            
            # skip line if query is empty
            if not query:
                continue
            
            # if no results exist at all in existing data set, search is a-go as before;
            # otherwise constrain search to avoid redundancy
            if articles is not None:
                if np.size(articles[databaseindices==counter]) == 0:
                    missing = 'All'
                else:
                    count = min([int(a['resultscount']) for a in articles[databaseindices==counter] if a['parents'] == 0])
                    missing = set(np.arange(1, count+1)) - set([int(s['searchindex']) for s in articles[databaseindices==counter]])
            else:
                missing = 'All'
            
            # don't do any search if no results are missing for this event
            if not missing:
                continue
    
            totalsearches += 1
            logging.warning(counter)
            logging.warning(missing)
            yield scrapy.Request('https://search.proquest.com/advanced.showresultpageoptions?site=news',
                                     callback=self.startform, dont_filter=True, 
                                     meta={'originalquery': query, 'query': query, 'databaseindex': counter,
                                           'originalstart': d0, 'originalend': d1, 'line': line, 
                                           'querystart': d0, 'queryend': d1, 'parents': 0, 'missing': missing}
                                )
        tqdm.close()
            
     # starts the form that must be filled out to search w/ our query
    def startform(self, response):
        # start the search form
        yield scrapy.Request('https://search.proquest.com/news/advanced?accountid=13314',
                             callback=self.query, dont_filter=True, meta=response.meta)
    
    # fills out form and initiates search
    def query(self, response):
        # fill it out and search
        yield scrapy.FormRequest.from_response(response, dont_filter=True, formid='searchForm',
                                               formdata={'queryTermField': response.meta['query'],'fullTextLimit':'on',
                                                         'sortType':'DateAsc', 'includeDuplicate':'on'},
                                               callback=self.parsePages, clickdata={'id': 'searchToResultPage'},
                                               meta=response.meta)
    
    # sets up inspection of each page of results generated by search
    def parsePages(self, response):

        sel = Selector(response)
        if 'sessionexpired' in response.url:
            logging.warning('Session Expiration Outcome Tied To {}'.format(response.meta['databaseindex']))
            return
        try:
            resultscount = sel.xpath("//h1[@id='pqResultsCount']/text()").extract()[0]
        except IndexError:
            logging.warning('Result Absence Outcome Tied To {}'.format(response.meta['databaseindex']))
            return
        resultscount = int(resultscount[:resultscount.find(' ')].replace(',', ''))
        maxpages = resultscount // 100
        urlparts = [response.url[:response.url.find('/1')+1], response.url[response.url.find('1?')+1:]]

        # what i do next depends on what's missing
        # for each result page, grab and parse it if a needed result is missing
        # if there's a missing result beyond the max possible recount, open the final result page at the end of the loop
        for page_index in range(min(maxpages+1, maxpossiblepages)):
            request = scrapy.Request(str(page_index+1).join(urlparts), callback=self.parse, dont_filter=True, meta=response.meta)

            if response.meta['missing'] is 'All':
                yield request
            elif 0 < len(set(np.arange((page_index*100)+1+(response.meta['parents']*maxpossiblepages*100),min((page_index+1)*100+(response.meta['parents']*maxpossiblepages*100),
                                                                                     resultscount+(response.meta['parents']*maxpossiblepages*100))+1)
                   ).intersection(response.meta['missing'])):
                yield request
            elif page_index+1 == maxpossiblepages and len([m for m in response.meta['missing'] if m > maxpossiblepages*100]) > 0:
                yield request
            
    def parse(self, response):
        sel = Selector(response)
        if 'sessionexpired' in response.url:
            logging.warning('Session Expiration Outcome Tied To {}'.format(response.meta['databaseindex']))
            return
        try:
            resultscount = sel.xpath("//h1[@id='pqResultsCount']/text()").extract()[0]
        except IndexError:
            logging.warning('Result Absence Outcome Tied To {}'.format(response.meta['databaseindex']))
            return
        resultscount = int(resultscount[:resultscount.find(' ')].replace(',', ''))
        
        indices = sel.xpath("//li[@class='resultItem ltr']/div//span[@class='indexing']/text()").extract()
        titles = sel.xpath("//h3/a/@title").extract()
        links = sel.xpath("//h3/a/@href").extract()
        info = [(' '.join(path.xpath(".//span[@class='titleAuthorETC']//text()").extract())).replace('\n', '') for path in sel.xpath("//li[@class='resultItem ltr']")]

        # try to extract date from each article's info
        
        dates = [parseDate(each, response.meta['originalstart'], scrape_window+1) for each in info]
        
        # correct me if im wrong but i assume all of these lists are of the same length
        assert (len(indices) + len(titles) + len(links) + len(info) + len(dates)) == (len(indices) + len(indices) + len(indices) + len(indices) + len(indices))
        
        # now populate an ArticleItem() for each result
        for i in range(len(indices)):
            
            # but skip if missing parameter suggests that the articleitem has already been processed
            if response.meta['missing'] is not 'All':
                if int(indices[i]) + response.meta['parents']*maxpossiblepages*100 not in response.meta['missing']:
                    continue
            
            article = ArticleItem()
            
            # defined by database
            article['databaseindex'] = response.meta['databaseindex']
            
            # defined prior to or at start of search
            article['resultscount'] = resultscount + response.meta['parents']*maxpossiblepages*100
            article['originalquery'] = response.meta['originalquery']
            article['originalstart'] = str(response.meta['originalstart'])
            article['originalend'] = str(response.meta['originalend'])
            article['query'] = response.meta['query']
            article['querystart'] = str(response.meta['querystart'])
            article['queryend'] = str(response.meta['queryend'])
            article['parents'] = int(response.meta['parents'])

            # defined by item itself
            article['searchindex'] = int(indices[i]) + response.meta['parents']*maxpossiblepages*100
            article['title'] = titles[i]
            article['info'] = info[i]
            article['link']  = links[i]

            # derived from those above
            article['daysFrom'] = str(dates[i])
            yield article
            
        # set up successive searches for when there are more than max possible results
        limitstring = 'You have reached the maximum number of search results that are displayed.'
        limit = sel.xpath("//p[@class='errorMessageHeaderText']/text()")
        if limit:
            if limitstring in limit.extract()[0]:
                request = scrapy.Request('https://search.proquest.com/advanced.showresultpageoptions?site=news',
                                         callback=self.startform, dont_filter=True, meta=response.meta)
                
                request.meta['parents'] += 1
                request.meta['querystart'] = [d for d in dates if d is not None][-1]
                request.meta['query'] = searchParamGenerators[event_type](request.meta['line'], header, d0=request.meta['querystart'], d1=request.meta['queryend'])[0]
                yield request


# -

# ### Spider Execution

# +
process = CrawlerProcess({'USER_AGENT': 'Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 5.1)'})

process.crawl(articleSpider)
process.start()
# -


