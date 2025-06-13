DIRNAME := $(shell basename $(CURDIR))
CHARMFILE := microcluster-token-distributor_amd64.charm

build: $(CHARMFILE)

$(CHARMFILE): src/charm.py charmcraft.yaml
	charmcraft pack -v

secret:
	charmcraft login \
		--export=secret \
		--charm=microcluster-token-distributor \
		--permission=package-manage-metadata \
		--permission=package-manage-releases \
		--permission=package-manage-revisions \
		--permission=package-view-metadata \
		--permission=package-view-releases \
		--permission=package-view-revisions \
		--ttl=31536000  # 365 days

clean:
	charmcraft clean
	rm $(CHARMFILE) -f
	rm -f .charmhub.secret
