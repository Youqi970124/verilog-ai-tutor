`timescale 1 ps/1 ps
`define OK 12
`define INCORRECT 13


module stimulus_gen (
	input clk,
	output logic a,
	output logic b,
	output logic c,
	output logic d
);

	initial begin
		@(posedge clk) begin a <= 1'd1; b <= 1'd0; c <= 1'd0; d <= 1'd0; end
		@(posedge clk) begin a <= 1'd0; b <= 1'd1; c <= 1'd0; d <= 1'd0; end
		@(posedge clk) begin a <= 1'd0; b <= 1'd0; c <= 1'd1; d <= 1'd0; end
		@(posedge clk) begin a <= 1'd0; b <= 1'd0; c <= 1'd0; d <= 1'd1; end
		@(posedge clk) begin a <= 1'd1; b <= 1'd1; c <= 1'd1; d <= 1'd1; end
		@(posedge clk) begin a <= 1'd1; b <= 1'd0; c <= 1'd1; d <= 1'd0; end
		repeat(300) @(posedge clk, negedge clk) begin a <= $random; b <= $random; c <= $random; d <= $random; end
		#1 $finish;
	end

endmodule

module tb();

	typedef struct packed {
		int errors;
		int errortime;
		int errors_out1;
		int errortime_out1;
		int errors_out2;
		int errortime_out2;

		int clocks;
	} stats;

	stats stats1;

	reg clk=0;
	initial forever
		#5 clk = ~clk;

	logic a;
	logic b;
	logic c;
	logic d;
	logic out1_ref;
	logic out1_dut;
	logic out2_ref;
	logic out2_dut;

	initial begin
		$dumpfile("wave.vcd");
		$dumpvars(1, stim1.clk, tb_mismatch, a, b, c, d, out1_ref, out1_dut, out2_ref, out2_dut);
	end

	wire tb_match;
	wire tb_mismatch = ~tb_match;

	stimulus_gen stim1 (.clk, .a, .b, .c, .d);
	RefModule good1 (.a, .b, .c, .d, .out1(out1_ref), .out2(out2_ref));
	TopModule top_module1 (.a, .b, .c, .d, .out1(out1_dut), .out2(out2_dut));

	final begin
		if (stats1.errors_out1) $display("Hint: Output '%s' has %0d mismatches. First mismatch occurred at time %0d.", "out1", stats1.errors_out1, stats1.errortime_out1);
		else $display("Hint: Output '%s' has no mismatches.", "out1");
		if (stats1.errors_out2) $display("Hint: Output '%s' has %0d mismatches. First mismatch occurred at time %0d.", "out2", stats1.errors_out2, stats1.errortime_out2);
		else $display("Hint: Output '%s' has no mismatches.", "out2");
		$display("Hint: Total mismatched samples is %1d out of %1d samples\n", stats1.errors, stats1.clocks);
		$display("Simulation finished at %0d ps", $time);
		$display("Mismatches: %1d in %1d samples", stats1.errors, stats1.clocks);
	end

	assign tb_match = ( { out1_ref, out2_ref } === ( { out1_ref, out2_ref } ^ { out1_dut, out2_dut } ^ { out1_ref, out2_ref } ) );

	always @(posedge clk, negedge clk) begin
		stats1.clocks++;
		if (!tb_match) begin
			if (stats1.errors == 0) stats1.errortime = $time;
			stats1.errors++;
		end
		if (out1_ref !== ( out1_ref ^ out1_dut ^ out1_ref ))
		begin if (stats1.errors_out1 == 0) stats1.errortime_out1 = $time;
			stats1.errors_out1 = stats1.errors_out1+1'b1; end
		if (out2_ref !== ( out2_ref ^ out2_dut ^ out2_ref ))
		begin if (stats1.errors_out2 == 0) stats1.errortime_out2 = $time;
			stats1.errors_out2 = stats1.errors_out2+1'b1; end
	end

	initial begin
		#1000000
		$display("TIMEOUT");
		$finish();
	end

endmodule
