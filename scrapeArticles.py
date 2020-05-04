# # scrapeArticles
# A notebook for scraping news article data from the ProQuest Newspapers Archive via `scrapy`. A user with archive access should be able to specify search parameters and upon execution obtain an organized list of all relevant articles mentioned in the archive, including all metadata necessary to reproduce or locate any particular result.
#
# ## Source Overview
# ProQUEST should be explained here (and what we're doing with it should probably be explained in more detail above).

# ## Dependencies
# Here we specify the libraries and basic data that our article scraping pipeline depends on to operate.

# +
# for math
import datetime
from datetime import timedelta
import numpy as np
import math
import time

# for scraping and storing data
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
# -

# ## Search Space
# Here we define the space across ProQUEST for our news articles search. For now, we'll just assume only a single search `query` is a parameter varied from search to search.

# +
# identify directory where data will be stored with a name for the current research topic
topic = 'biden'

# what will be searched
query = 'biden' 

# must specify a date range (d0 to d1) so we can ensure search completeness later on. if not interested in constraining dates, just include every relevant date!
# articles published on d0 up to but excluding d1 will be collected
d0 = parser.parse('May 1, 2020')
d1 = parser.parse('May 2, 2020')
# -

# ## Scraping Pipeline
# Here we'll define our web crawler and its process for traversing and extracting the data we want from ProQUEST.
#
# ### Minor Details
#
# #### We will load/organize already existing dataset so we can avoid redundant scraping
# We assume that the data will be located at `data/articles.jsonl` within a directory associated with the current research `topic`.

try:
    articles = []
    with open(os.path.join(topic, 'data', 'articles.jsonl')) as f:
        for line in f:
            articles.append(json.loads(line))
    articles = np.array(articles)
except FileNotFoundError:
    articles = None


# #### We'll organize scraped information into an ArticleItem instance to facilitate orderly storage.
# There are two types of information we currently store: 
# - **Information about the search process**. Every detail identifying we found this article using this pipeline so that anyone who wants to check our work (including ourselves) can do it.
# - **Information about the article**. Just meta-data for now rather than content. Stuff like title, publication, date, URL, etc.

class ArticleItem(scrapy.Item):
    
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


# #### We'll store Article Data as JSON lines.
# This `JsonWriterPipeline` class specifies exactly what happens when a new `ArticleItem` instance is prepared. We'll store all scraped items into a single `articles.jsonl`, listing each research as a unique JSON object.
#
# `JSON` is just a human-readable way of representing dictionaries as text. With the `json` package, they can be readily loaded into Python dictionaries or converted into other formats.

class JsonWriterPipeline(object):

    # operations performed when spider starts
    def open_spider(self, spider):
        self.file = open(os.path.join(topic, 'data', 'articles.jsonl'), 'a')

    # when the spider finishes
    def close_spider(self, spider):
        self.file.close()

    # when the spider yields an item
    def process_item(self, item, spider):
        line = json.dumps(dict(item)) + "\n"
        self.file.write(line)
        return item 


# ### Crawler Settings and Initial URL(s)
# The initial URL isn't actually the search form. Instead, we go to a URL that for some unknown reason must be visited first in order to have access to all possible search parameters with a web crawler. Query information is maintained in a `meta` field within the request so we use (and ultimately store) the information downstream.

class articleSpider(scrapy.Spider):
    name = 'articles'
    custom_settings = {'HTTPERROR_ALLOWED_CODES': [500],
                      'ITEM_PIPELINES': {'__main__.JsonWriterPipeline': 1},
                      'LOG_LEVEL': 'WARNING'}
    
    def start_requests(self):
        
        # if no results exist at all in existing data set, search is a-go as before;
        # otherwise constrain search to avoid redundancy
        # this is a powerful way to test if and ensure our traversal actually succeeded
        # since proquest will inevitably reject some request, some drop-outs are inevitable and must be tracked/corrected
        if articles is not None:
            if np.size(articles) == 0:
                missing = 'All'
            else:
                count = min([int(a['resultscount']) for a in articles if a['parents'] == 0])
                missing = set(np.arange(1, count+1)) - set([int(s['searchindex']) for s in articles])
        else:
            missing = 'All'
        
        yield scrapy.Request('https://search.proquest.com/advanced.showresultpageoptions?site=news',
                                 callback=self.startform, dont_filter=True, 
                                 meta={'originalquery': query, 'query': query, 'databaseindex': 0,
                                       'originalstart': d0, 'originalend': d1, 'line': '',
                                       'querystart': d0, 'queryend': d1, 'parents': 0, 'missing': missing}
                            )


# ### Querying for Results
# We have to make a request to start the full search form and then another request to actually initiate the search query.

# +
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


# -

# ### Planning Traversal of Result Pages
# We generate a unique request for each page of the search results. Furthermore, since ProQUEST returns a maximum number of results associated with a particular search query that may be smaller than the number of *true* matching results, we may have to prepare to generate new searches excluding already returned results so that the missing results can be collected too.
#
# At the same time, we avoid querying for pages whose results are already stored in the relevant `data/articles.jsonl`.

# sets up inspection of each page of results generated by search
def parsePages(self, response):

    sel = Selector(response)
    
    # sometimes proquest will expire the current session or refuse to fulfill a query
    # we'll have to get them another time!
    if 'sessionexpired' in response.url:
        logging.warning('Session Expiration Outcome Tied To {}'.format(response.meta['databaseindex']))
        return
    
    # we check if there are no results provided for some other reason and also log/give up when that happens
    try:
        resultscount = sel.xpath("//h1[@id='pqResultsCount']/text()").extract()[0]
    except IndexError:
        logging.warning('Result Absence Outcome Tied To {}'.format(response.meta['databaseindex']))
        return
    
    # on this page we can count the number of returned results and construct follow-up queries on that basis
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


# ### Parsing Results For Data

def parse(self, response):
        sel = Selector(response)
        
        # sometimes proquest will expire the current session or refuse to fulfill a query
        # we'll have to get them another time!
        if 'sessionexpired' in response.url:
            logging.warning('Session Expiration Outcome Tied To {}'.format(response.meta['databaseindex']))
            return
        
        # we check if there are no results provided for some other reason and also log/give up when that happens
        try:
            resultscount = sel.xpath("//h1[@id='pqResultsCount']/text()").extract()[0]
        except IndexError:
            logging.warning('Result Absence Outcome Tied To {}'.format(response.meta['databaseindex']))
            return
        resultscount = int(resultscount[:resultscount.find(' ')].replace(',', ''))
        
        # we pull the data from the results page for parsing
        indices = sel.xpath("//li[@class='resultItem ltr']/div//span[@class='indexing']/text()").extract()
        titles = sel.xpath("//h3/a/@title").extract()
        links = sel.xpath("//h3/a/@href").extract()
        info = [(' '.join(path.xpath(".//span[@class='titleAuthorETC']//text()").extract())).replace('\n', '') for path in sel.xpath("//li[@class='resultItem ltr']")]
        
        # correct me if im wrong but i assume all of these lists are of the same length
        assert (len(indices) + len(titles) + len(links) + len(info) + len(dates)) == (len(indices) + len(indices) + len(indices) + len(indices) + len(indices))
        
        # now populate an ArticleItem() for each result
        for i in range(len(indices)):
            
            # but skip if missing parameter suggests that the articleitem has already been processed
            if response.meta['missing'] is not 'All':
                if int(indices[i]) + response.meta['parents']*maxpossiblepages*100 not in response.meta['missing']:
                    continue
            
            article = ArticleItem()
            
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


# ### Spider Execution

# +
articleSpider.startform = startform
articleSpider.query = query
articleSpider.parsePages = parsePages
articleSpider.parse = parse

process = CrawlerProcess({'USER_AGENT': 'Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 5.1)'})

process.crawl(articleSpider)
process.start()
# -


