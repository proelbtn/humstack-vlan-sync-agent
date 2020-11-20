FROM python:3.8

RUN mkdir -p /app
WORKDIR /app

RUN pip install pipenv

COPY Pipfile Pipfile.lock ./
RUN pipenv lock -r > requirements.txt
RUN pip install -r requirements.txt

COPY main.py ./
COPY config.yml ./

CMD [ "python", "-u", "main.py" ]
