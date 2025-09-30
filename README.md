# Twitter Scraper (推特爬虫)
This is a twtter scraper that can scrape a twitter account's post.
## How to use
**1. Install requirements<br>**
```python
pip install -r requirements.txt
```
**2. Get your cookies<br>**
```python
python -m src.login --user "username" --password "password"
```
then cookies will be saved in twitter_cookies.json<br>
**3. Run the client<br>**
```python
python -m src.cli --user "username" --limit 30 --out output.json --format json
```