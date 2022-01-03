#!/bin/bash
# Script to run metaindexmanger as the file selector for attachments in
# (neo)mutt

rc=/run/user/$(id -u)/mtattach.rc
echo "cd ." > $rc

if [ -z "`which metaindexmanager`" ]
then
    echo "push <attach-file>" > $rc
else
    FILENAME=$(mktemp -p /run/user/`id -u`/)
    metaindexmanager --select-file-mode --select-file-output=$FILENAME
    ATTACHMENT="$(cat $FILENAME)"
    if [ -n "$ATTACHMENT" ]
    then
        echo "push <attach-file>\"$ATTACHMENT\"<return>" > $rc
    fi
    rm -f $FILENAME
fi

