FROM alpine
RUN apk add --no-cache git jq bash

# docker build . -f tools/Dockerfile --tag repositories
# docker run -d --rm --name repositories repositories sleep 3600
# docker exec -it repositories bash
# docker kill repositories (when done)

# Find stuff with 'grep -Ri "string_to_find" /<base_path>'

# COPY ./netdaemon /data/
# RUN \
#     for entry in $(jq -r .[]  /data/netdaemon); do\
#         git clone --depth 1 "https://github.com/${entry}.git" "/netdaemon/${entry}";\
#     done
#
#
# COPY ./appdaemon /data/
# RUN \
#     for entry in $(jq -r .[]  /data/appdaemon); do\
#         git clone --depth 1 "https://github.com/${entry}.git" "/appdaemon/${entry}";\
#     done
#
#
# COPY ./python_script /data/
# RUN \
#     for entry in $(jq -r .[]  /data/python_script); do\
#         git clone --depth 1 "https://github.com/${entry}.git" "/python_script/${entry}";\
#     done
#
# COPY ./template /data/
# RUN \
#     for entry in $(jq -r .[]  /data/template); do\
#         git clone --depth 1 "https://github.com/${entry}.git" "/template/${entry}";\
#     done
#
#
# COPY ./theme /data/
# RUN \
#     for entry in $(jq -r .[]  /data/theme); do\
#         git clone --depth 1 "https://github.com/${entry}.git" "/theme/${entry}";\
#     done
#
#
# COPY ./plugin /data/
# RUN \
#     for entry in $(jq -r .[]  /data/plugin); do\
#         git clone --depth 1 "https://github.com/${entry}.git" "/plugin/${entry}";\
#     done
#
#
# COPY ./integration /data/
# RUN \
#     for entry in $(jq -r .[]  /data/integration); do\
#         git clone --depth 1 "https://github.com/${entry}.git" "/integration/${entry}";\
#     done
