Output "/tmp/swarmmesh-demo/docs/demo-status.gif"
Set FontSize 16
Set Width 760
Set Height 260
Set Theme "Dracula"
Set WindowBar Colorful
Set WindowBarSize 36

Type "export PS1='$ '"
Enter
Sleep 300ms

Type "swarmmesh serve --port 8433 &"
Enter
Sleep 1s

Type "swarmmesh agent register mesh-worker-2 coordinator --port 8433 --json"
Enter
Sleep 1s

Type "swarmmesh agent list --port 8433 --json"
Enter
Sleep 1s

Type "swarmmesh status --port 8433 --json"
Enter
Sleep 1s

Type `swarmmesh context set fleet-status health '"all agents nominal"' --agent-id mesh-worker-2 --port 8433 --json`
Enter
Sleep 1s

Type "swarmmesh context list fleet-status --port 8433 --json"
Enter
Sleep 1.5s
