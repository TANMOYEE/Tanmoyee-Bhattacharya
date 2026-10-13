FROM python:3.11-slim
RUN pip install --no-cache-dir pytest==8.3.4
WORKDIR /tests
COPY test_task.py /tests/test_task.py
COPY test.sh /tests/test.sh
RUN chmod 755 /tests/test.sh
COPY data/ /tests/data/
# Provide the primary reference CSV in the verifier container; the candidate source is separately checked through declared artifacts when mounted.
RUN mkdir -p /root/data && cp /tests/data/original_river_event_observations.csv /root/data/river_event_observations.csv
RUN chown -R root:root /tests /root && chmod 700 /tests/data && chmod 600 /tests/data/*.csv /tests/test_task.py && mkdir -p /root/results && chown root:root /root/results && chmod 755 /root/results
