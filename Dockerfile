FROM nikolaik/python-nodejs:python3.10-nodejs12
WORKDIR /app

COPY package.json package-lock.json /app/
RUN npm install

COPY main.js progress.js concurrency.js /app/

# ADD memories_history.json /app/
ENTRYPOINT [ "node", "main.js" ]

# CMD [ "-c", "50", "-o", "Downloads", "-f", "/app/json/memories_history.json" ]
CMD [ "--help" ]
