DIRNAME := $(shell basename $(CURDIR))
CHARMFILE := microcluster-token-distributor_amd64.charm

build: $(CHARMFILE)

$(CHARMFILE): src/charm.py charmcraft.yaml
	charmcraft pack -v

clean:
	charmcraft clean
	rm $(CHARMFILE) -f
